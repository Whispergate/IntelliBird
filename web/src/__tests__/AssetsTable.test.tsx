// Owned by: 12.1-05-PLAN

import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import {
  AssetsTable,
  type AssetRow,
  type AssetSortState,
} from "@/app/projects/[id]/assets/components/AssetsTable";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const THREE_ROWS: AssetRow[] = [
  {
    asset_id: "a1",
    bbot_event_type: "DNS_NAME",
    canonical_target: "www.example.com",
    scope: "in_scope",
    first_seen: "2026-01-01T00:00:00Z",
    last_seen: "2026-04-20T00:00:00Z",
    scan_count: 3,
    modules: ["subdomain-brute", "sslcert"],
    stale: false,
  },
  {
    asset_id: "a2",
    bbot_event_type: "IP_ADDRESS",
    canonical_target: "203.0.113.9",
    scope: "out_of_scope",
    first_seen: "2026-01-05T00:00:00Z",
    last_seen: "2026-04-18T00:00:00Z",
    scan_count: 1,
    modules: ["nmap"],
    stale: true,
  },
  {
    asset_id: "a3",
    bbot_event_type: "URL",
    canonical_target: "https://api.example.com/v1/auth",
    scope: "unscoped",
    first_seen: "2026-02-01T00:00:00Z",
    last_seen: "2026-04-10T00:00:00Z",
    scan_count: 2,
    modules: ["httpx", "wappalyzer", "waf", "gowitness"],
    stale: false,
  },
];

const DEFAULT_SORT: AssetSortState = { key: "last_seen", direction: "desc" };

function renderTable(
  overrides: Partial<React.ComponentProps<typeof AssetsTable>> = {},
) {
  const onSortChange = vi.fn();
  const onRowClick = vi.fn();
  const onPageChange = vi.fn();
  const props: React.ComponentProps<typeof AssetsTable> = {
    rows: THREE_ROWS,
    sort: DEFAULT_SORT,
    onSortChange,
    onRowClick,
    pagination: {
      page: 1,
      pageSize: 50,
      total: 52,
      onPageChange,
    },
    ...overrides,
  };
  render(<AssetsTable {...props} />);
  return { onSortChange, onRowClick, onPageChange };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AssetsTable (12.1-05b)", () => {
  it("renders all 9 columns with exact labels + locked order", () => {
    renderTable();
    const headerRow = screen.getAllByRole("row")[0];
    const headers = within(headerRow).getAllByRole("columnheader");
    expect(headers).toHaveLength(9);
    expect(headers[0]).toHaveTextContent("Type");
    expect(headers[1]).toHaveTextContent("Target");
    expect(headers[2]).toHaveTextContent("Scope");
    expect(headers[3]).toHaveTextContent("First seen");
    expect(headers[4]).toHaveTextContent("Last seen");
    expect(headers[5]).toHaveTextContent("Scans");
    expect(headers[6]).toHaveTextContent("Modules");
    expect(headers[7]).toHaveTextContent("Stale");
    // 9th header (actions) has no visible label
    expect(headers[8]).toBeInTheDocument();
  });

  it("scope chip classes match for each of in_scope / out_of_scope / unscoped", () => {
    renderTable();
    const rowsEls = screen.getAllByTestId("assets-row");
    expect(rowsEls).toHaveLength(3);

    const inScopeChip = within(rowsEls[0]).getByText("in scope");
    expect(inScopeChip.className).toContain("bg-teal-900/40");
    expect(inScopeChip.className).toContain("text-teal-300");

    const outOfScopeChip = within(rowsEls[1]).getByText("out of scope");
    expect(outOfScopeChip.className).toContain("border-destructive");
    expect(outOfScopeChip.className).toContain("text-destructive");

    const unscopedChip = within(rowsEls[2]).getByText("unscoped");
    expect(unscopedChip.className).toContain("bg-muted");
    expect(unscopedChip.className).toContain("text-muted-foreground");
  });

  it("stale pill renders only when stale=true (with muted tokens, NOT signal-amber)", () => {
    renderTable();
    // Filter out the column header <th> — only count rendered badge pills.
    const pills = screen
      .getAllByText("Stale")
      .filter((el) => el.tagName.toLowerCase() !== "th");
    // Only row with stale=true (a2)
    expect(pills).toHaveLength(1);
    expect(pills[0].className).toContain("bg-muted");
    expect(pills[0].className).toContain("text-muted-foreground");
    expect(pills[0].className).not.toContain("var(--brand-signal)");
  });

  it("row click fires onRowClick with asset_id", () => {
    const { onRowClick } = renderTable();
    const rowsEls = screen.getAllByTestId("assets-row");
    fireEvent.click(rowsEls[0]);
    expect(onRowClick).toHaveBeenCalledTimes(1);
    expect(onRowClick).toHaveBeenCalledWith("a1");
  });

  it("Enter key on focused row fires onRowClick", () => {
    const { onRowClick } = renderTable();
    const rowsEls = screen.getAllByTestId("assets-row");
    fireEvent.keyDown(rowsEls[1], { key: "Enter" });
    expect(onRowClick).toHaveBeenCalledWith("a2");
  });

  it("pagination text reads 'Page 1 of 2 — 50 per page' when total=52", () => {
    renderTable();
    const text = screen.getByTestId("assets-pagination-text");
    // NB: em-dash \u2014 between "of 2" and "50 per page"
    expect(text.textContent).toBe("Page 1 of 2 \u2014 50 per page");
  });

  it("Previous button disabled at page 1 (offset 0)", () => {
    renderTable();
    const prev = screen.getByRole("button", { name: "Previous" });
    expect(prev).toBeDisabled();
  });
});
