/**
 * ScopeRowTable.test.tsx — -01 (UX-01 audit + test coverage)
 *
 * Asserts that all three toggle fields in ScopeRowTable (exclude, active_test_scope,
 * intel_scope) fire a single PATCH call via updateScopeRow and NEVER call
 * deleteScopeRow. Also tests:
 *   - optimistic-update revert on PATCH 5xx (toast.error + reload)
 *   - frontend pre-flight gate: active_test_scope=false when intel_scope already
 *     false triggers toast, NOT a PATCH call
 *
 * UX-01 audit verdict (confirmed by reading all three source files):
 *
 * Step 1 — ScopeRowTable.tsx:84-106
 *   Three <Switch> components each call onToggle(row, { field: v }) with a
 *   single-key patch object: { exclude: v }, { active_test_scope: v }, { intel_scope: v }.
 *
 * Step 2 — ScopeTabContent.tsx:167-179
 *   handleToggle builds merged = { ...row, ...patch }. Pre-flight check:
 *   if (!merged.active_test_scope && !merged.intel_scope) { toast.error(...); return; }
 *   This mirrors the backend CHECK constraint project_scope_rows_at_least_one_flag.
 *
 * Step 3 — ScopeTabContent.tsx:181-185
 *   Optimistic update: setRows(prev => prev.map(...)) applied immediately.
 *   Then: await updateScopeRow(project.id, row.id, patch) — single PATCH call.
 *
 * Step 4 — projects/lib/api.ts:374-383
 *   updateScopeRow calls _apiFetch PATCH. No DELETE+POST anywhere.
 *   deleteScopeRow is wired ONLY to the explicit Delete icon button, not toggles.
 *
 * Step 5 — ScopeTabContent.tsx:186-190
 *   catch: toast.error("Could not update row. ...") + await reload() (full revert).
 *
 * Audit verdict: UX-01 is fully implemented. No code path falls back to DELETE+POST.
 * PROJECT.md note " carry-over" was stale text.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mock @/app/projects/lib/api — spy on updateScopeRow and deleteScopeRow
// ---------------------------------------------------------------------------
vi.mock("@/app/projects/lib/api", () => ({
  listScopeRows: vi.fn(),
  addScopeRow: vi.fn(),
  deleteScopeRow: vi.fn(),
  updateScopeRow: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Mock sonner toast
// ---------------------------------------------------------------------------
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

import {
  listScopeRows,
  updateScopeRow,
  deleteScopeRow,
} from "@/app/projects/lib/api";
import { toast } from "sonner";
import { ScopeTabContent } from "@/app/projects/[id]/ScopeTabContent";
import type { ProjectResponse, ScopeRowResponse } from "@/app/projects/lib/api";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

const FAKE_PROJECT: ProjectResponse = {
  id: "proj-a",
  name: "Alpha",
  engagement_type: "internal",
  description: null,
  created_by: "user-1",
  archived: false,
  active_scans_authorised: false,
  scope_acknowledgement_text: null,
  active_auth_confirmed_at: null,
  active_auth_confirmed_by: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  member_count: 1,
  creator_is_current_user: true,
};

/** A domain scope row that satisfies the at-least-one invariant: intel_scope=true, active_test_scope=false */
function makeRow(overrides: Partial<ScopeRowResponse> = {}): ScopeRowResponse {
  return {
    id: "row-1",
    project_id: "proj-a",
    scope_type: "domain",
    value: "example.com",
    contact: null,
    exclude: false,
    active_test_scope: false,
    intel_scope: true,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const listScopeRowsMock = vi.mocked(listScopeRows);
const updateScopeRowMock = vi.mocked(updateScopeRow);
const deleteScopeRowMock = vi.mocked(deleteScopeRow);
const toastErrorMock = vi.mocked(toast.error);

beforeEach(() => {
  listScopeRowsMock.mockReset();
  updateScopeRowMock.mockReset();
  deleteScopeRowMock.mockReset();
  toastErrorMock.mockReset();
  vi.mocked(toast.success).mockReset();
});

/** Render ScopeTabContent with one pre-loaded row. tabKey="scope-domain" maps to scope_type="domain". */
async function renderWithRow(row: ScopeRowResponse) {
  // listScopeRows is called in useEffect on mount — return the single row.
  listScopeRowsMock.mockResolvedValue([row]);

  let container: HTMLElement;
  await act(async () => {
    const result = render(
      <ScopeTabContent project={FAKE_PROJECT} tabKey="scope-domain" />,
    );
    container = result.container;
  });

  // Wait for the row to appear (loading state resolves).
  await waitFor(() => {
    expect(screen.getByText("example.com")).toBeInTheDocument();
  });

  return { container: container! };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ScopeRowTable toggle — fires PATCH not DELETE+POST (UX-01)", () => {
  it("Test 1: toggles exclude via single PATCH (not DELETE+POST)", async () => {
    const row = makeRow({ exclude: false });
    updateScopeRowMock.mockResolvedValue({ ...row, exclude: true });

    await renderWithRow(row);

    const excludeSwitch = screen.getByRole("switch", { name: /exclude flag/i });
    await userEvent.click(excludeSwitch);

    await waitFor(() => {
      expect(updateScopeRowMock).toHaveBeenCalledTimes(1);
    });
    expect(updateScopeRowMock).toHaveBeenCalledWith("proj-a", "row-1", {
      exclude: true,
    });
    expect(deleteScopeRowMock).not.toHaveBeenCalled();
  });

  it("Test 2: toggles active_test_scope via single PATCH (not DELETE+POST)", async () => {
    const row = makeRow({ active_test_scope: false, intel_scope: true });
    updateScopeRowMock.mockResolvedValue({ ...row, active_test_scope: true });

    await renderWithRow(row);

    const activeSwitch = screen.getByRole("switch", {
      name: /active-test-scope flag/i,
    });
    await userEvent.click(activeSwitch);

    await waitFor(() => {
      expect(updateScopeRowMock).toHaveBeenCalledTimes(1);
    });
    expect(updateScopeRowMock).toHaveBeenCalledWith("proj-a", "row-1", {
      active_test_scope: true,
    });
    expect(deleteScopeRowMock).not.toHaveBeenCalled();
  });

  it("Test 3: toggles intel_scope via single PATCH (not DELETE+POST)", async () => {
    // Row has both true so toggling intel_scope false still leaves active_test_scope true.
    const row = makeRow({ intel_scope: true, active_test_scope: true });
    updateScopeRowMock.mockResolvedValue({ ...row, intel_scope: false });

    await renderWithRow(row);

    const intelSwitch = screen.getByRole("switch", {
      name: /intel-scope flag/i,
    });
    await userEvent.click(intelSwitch);

    await waitFor(() => {
      expect(updateScopeRowMock).toHaveBeenCalledTimes(1);
    });
    expect(updateScopeRowMock).toHaveBeenCalledWith("proj-a", "row-1", {
      intel_scope: false,
    });
    expect(deleteScopeRowMock).not.toHaveBeenCalled();
  });

  it("Test 4: optimistic-update reverts on PATCH 5xx — toast.error + reload", async () => {
    const row = makeRow({ exclude: false });
    updateScopeRowMock.mockRejectedValueOnce(new Error("Server error"));
    // reload() calls listScopeRows again — return the original row (revert).
    listScopeRowsMock
      .mockResolvedValueOnce([row])  // initial load
      .mockResolvedValueOnce([row]); // reload after failure

    await renderWithRow(row);

    const excludeSwitch = screen.getByRole("switch", { name: /exclude flag/i });
    await userEvent.click(excludeSwitch);

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalled();
    });

    // Toast must contain "Could not update row"
    const toastCall = toastErrorMock.mock.calls[0][0];
    expect(typeof toastCall === "string" && toastCall.toLowerCase()).toContain(
      "could not update row",
    );

    // reload() was called to revert optimistic update — listScopeRows called again.
    await waitFor(() => {
      expect(listScopeRowsMock).toHaveBeenCalledTimes(2);
    });
  });

  it("Test 5: all-flags-false pre-flight gate — toast shown, updateScopeRow NOT called", async () => {
    // Row: intel_scope=false, active_test_scope=true. Toggling active_test_scope
    // false would zero BOTH flags — frontend pre-flight must block the PATCH.
    const row = makeRow({ intel_scope: false, active_test_scope: true });
    listScopeRowsMock.mockResolvedValue([row]);

    await act(async () => {
      render(<ScopeTabContent project={FAKE_PROJECT} tabKey="scope-domain" />);
    });
    await waitFor(() => {
      expect(screen.getByText("example.com")).toBeInTheDocument();
    });

    const activeSwitch = screen.getByRole("switch", {
      name: /active-test-scope flag/i,
    });
    await userEvent.click(activeSwitch);

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalled();
    });

    // The pre-flight error message (ScopeTabContent.tsx:177)
    const toastCall = toastErrorMock.mock.calls[0][0];
    expect(typeof toastCall === "string" && toastCall.toLowerCase()).toContain(
      "at least intel or active test",
    );

    // PATCH must NOT have been called — pre-flight stopped it.
    expect(updateScopeRowMock).not.toHaveBeenCalled();
  });
});
