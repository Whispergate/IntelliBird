/**
 * ScopeRowTooltip.test.tsx — Phase 20-03 (UX-03 display)
 *
 * Tests that ScopeRowTable wraps punycode domain values in a shadcn Tooltip
 * showing the decoded unicode form, while plain ASCII values and non-FQDN
 * scope types render as plain text with no tooltip trigger.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ScopeRowTable } from "@/app/projects/[id]/components/ScopeRowTable";
import type { ScopeRowResponse } from "@/app/projects/lib/api";

// ---------------------------------------------------------------------------
// Mock sonner for any toasts that might fire
// ---------------------------------------------------------------------------
vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRow(overrides: Partial<ScopeRowResponse>): ScopeRowResponse {
  return {
    id: "row-1",
    project_id: "proj-a",
    scope_type: "domain",
    value: "example.com",
    contact: null,
    exclude: false,
    active_test_scope: true,
    intel_scope: true,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const noop = () => Promise.resolve();

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ScopeRowTable — punycode Tooltip (UX-03)", () => {
  it("Test 1: renders tooltip trigger for punycode domain value", async () => {
    const row = makeRow({
      scope_type: "domain",
      value: "xn--bcher-kva.example",
    });
    render(
      <ScopeRowTable
        rows={[row]}
        scopeType="domain"
        onDelete={noop}
        onToggle={noop}
      />,
    );
    expect(screen.getByTestId("punycode-trigger")).toBeInTheDocument();

    // Hover to reveal tooltip content
    const user = userEvent.setup();
    await user.hover(screen.getByTestId("punycode-trigger"));

    // TooltipContent renders in a Portal — Radix renders both a visible div and
    // a visually-hidden ARIA span; use findAllByText and assert at least one match.
    const matches = await screen.findAllByText(/unicode:/i);
    expect(matches.length).toBeGreaterThan(0);
  });

  it("Test 2: renders plain text for ASCII domain (no xn-- prefix)", () => {
    const row = makeRow({ scope_type: "domain", value: "example.com" });
    render(
      <ScopeRowTable
        rows={[row]}
        scopeType="domain"
        onDelete={noop}
        onToggle={noop}
      />,
    );
    expect(screen.queryByTestId("punycode-trigger")).toBeNull();
    expect(screen.getByText("example.com")).toBeInTheDocument();
  });

  it("Test 3: renders plain text for non-FQDN scope_type even with xn-- prefix", () => {
    const row = makeRow({
      scope_type: "keyword",
      value: "xn--something",
    });
    render(
      <ScopeRowTable
        rows={[row]}
        scopeType="keyword"
        onDelete={noop}
        onToggle={noop}
      />,
    );
    expect(screen.queryByTestId("punycode-trigger")).toBeNull();
    expect(screen.getByText("xn--something")).toBeInTheDocument();
  });
});
