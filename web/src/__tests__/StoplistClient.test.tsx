/**
 * StoplistClient.test.tsx - (BRAND-01 frontend).
 *
 * Coverage:
 *   - Table renders with term/created_by/created_at columns (Lead role)
 *   - Add form (Input + Add button) visible for Lead; hidden for Observer and Contributor
 *   - Delete button visible for Lead; hidden for Observer and Contributor
 *   - Add term success → toast.success + term prepended + input cleared
 *   - Add term 409 conflict → toast.error with canonical copy
 *   - Delete term success → row removed + toast.success
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

// ---------------------------------------------------------------------------
// Mocks - hoisted before component imports
// ---------------------------------------------------------------------------

vi.mock("sonner", () => ({
  toast: {
    info: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/projects/proj-1/brand/stoplist",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock ProjectRoleProvider so we can control isLead/isObserver from outside
vi.mock(
  "@/app/projects/[id]/ProjectRoleProvider",
  async () => {
    const { createContext, useContext } = await import("react");

    type ProjectRoleContextValue = {
      role: string | null;
      isAdmin: boolean;
      isLead: boolean;
      isContributor: boolean;
      isObserver: boolean;
    };

    const ProjectRoleContext = createContext<ProjectRoleContextValue>({
      role: "Lead",
      isAdmin: false,
      isLead: true,
      isContributor: true,
      isObserver: false,
    });

    return {
      ProjectRoleProvider: ({
        value,
        children,
      }: {
        value: ProjectRoleContextValue;
        children: React.ReactNode;
      }) => (
        <ProjectRoleContext.Provider value={value}>
          {children}
        </ProjectRoleContext.Provider>
      ),
      useProjectRole: () => useContext(ProjectRoleContext),
    };
  },
);

import { toast } from "sonner";
import {
  ProjectRoleProvider,
} from "@/app/projects/[id]/ProjectRoleProvider";
import { StoplistClient } from "@/app/projects/[id]/brand/stoplist/StoplistClient";
import type { BrandStoplistTerm } from "@/app/projects/[id]/brand/stoplist/StoplistClient";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const TERM_1: BrandStoplistTerm = {
  id: "st-1",
  term: "noise.com",
  created_at: "2026-01-15T10:00:00Z",
  created_by_user_id: "user-abc-1234567890-xyzabc",
};

const TERM_2: BrandStoplistTerm = {
  id: "st-2",
  term: "spamword",
  created_at: "2026-02-01T08:30:00Z",
  created_by_user_id: null,
};

// ---------------------------------------------------------------------------
// Role context helpers
// ---------------------------------------------------------------------------

type RoleValues = {
  role: string | null;
  isAdmin: boolean;
  isLead: boolean;
  isContributor: boolean;
  isObserver: boolean;
};

const LEAD_ROLE: RoleValues = {
  role: "Lead",
  isAdmin: false,
  isLead: true,
  isContributor: true,
  isObserver: false,
};

const OBSERVER_ROLE: RoleValues = {
  role: "Observer",
  isAdmin: false,
  isLead: false,
  isContributor: false,
  isObserver: true,
};

const CONTRIBUTOR_ROLE: RoleValues = {
  role: "Contributor",
  isAdmin: false,
  isLead: false,
  isContributor: true,
  isObserver: false,
};

function renderWithRole(
  role: RoleValues,
  initialTerms: BrandStoplistTerm[] = [],
) {
  return render(
    // @ts-expect-error - test mock accepts value prop
    <ProjectRoleProvider value={role}>
      <StoplistClient projectId="proj-1" initialTerms={initialTerms} />
    </ProjectRoleProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StoplistClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ---- Role visibility gates ----------------------------------------------

  it("test_renders_table_lead: Lead sees table row, Add form, and Delete button", () => {
    renderWithRole(LEAD_ROLE, [TERM_1]);

    // Term appears in table
    expect(screen.getByText("noise.com")).toBeInTheDocument();

    // Add form visible
    expect(
      screen.getByPlaceholderText("Add term to stoplist"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /add term/i }),
    ).toBeInTheDocument();

    // Delete button visible
    expect(
      screen.getByRole("button", { name: /delete term/i }),
    ).toBeInTheDocument();
  });

  it("test_renders_observer: Observer sees read-only table; no Add form; no delete buttons; empty state copy", () => {
    renderWithRole(OBSERVER_ROLE, []);

    // Empty state renders
    expect(screen.getByText("No stoplist terms yet.")).toBeInTheDocument();

    // Observer sees different empty state body
    expect(
      screen.getByText("No terms have been added to the project stoplist."),
    ).toBeInTheDocument();

    // No add form
    expect(
      screen.queryByPlaceholderText("Add term to stoplist"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /add term/i }),
    ).not.toBeInTheDocument();
  });

  it("test_renders_contributor: Contributor sees read-only table; no Add form; no delete buttons", () => {
    renderWithRole(CONTRIBUTOR_ROLE, [TERM_1]);

    // Term visible
    expect(screen.getByText("noise.com")).toBeInTheDocument();

    // No add form
    expect(
      screen.queryByPlaceholderText("Add term to stoplist"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /add term/i }),
    ).not.toBeInTheDocument();

    // No delete buttons
    expect(
      screen.queryByRole("button", { name: /delete term/i }),
    ).not.toBeInTheDocument();
  });

  // ---- Add term -----------------------------------------------------------

  it("test_add_term_success: type term, click Add → fetch 201 → toast.success, term prepended, input cleared", async () => {
    const newTerm: BrandStoplistTerm = {
      id: "st-new",
      term: "noise.com",
      created_at: "2026-04-29T12:00:00Z",
      created_by_user_id: "user-xyz",
    };

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(newTerm), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const user = userEvent.setup();
    renderWithRole(LEAD_ROLE, [TERM_2]);

    const input = screen.getByPlaceholderText("Add term to stoplist");
    await user.type(input, "noise.com");

    const addBtn = screen.getByRole("button", { name: /add term/i });
    await user.click(addBtn);

    await waitFor(() => {
      expect(vi.mocked(toast.success)).toHaveBeenCalledWith(
        "Term added to stoplist.",
      );
    });

    // Term prepended (appears before existing term)
    expect(screen.getByText("noise.com")).toBeInTheDocument();
    expect(screen.getByText("spamword")).toBeInTheDocument();

    // Input cleared
    expect(input).toHaveValue("");
  });

  it("test_add_term_409: fetch returns 409 → toast.error with canonical copy", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "Term already in stoplist for this project." }),
        {
          status: 409,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const user = userEvent.setup();
    renderWithRole(LEAD_ROLE, []);

    await user.type(
      screen.getByPlaceholderText("Add term to stoplist"),
      "duplicate",
    );
    await user.click(screen.getByRole("button", { name: /add term/i }));

    await waitFor(() => {
      expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
        "Term already in stoplist for this project.",
      );
    });
  });

  // ---- Delete term --------------------------------------------------------

  it("test_delete_term: click Trash2 → fetch DELETE → row removed, toast.success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(null, { status: 204 }),
    );

    const user = userEvent.setup();
    renderWithRole(LEAD_ROLE, [TERM_1, TERM_2]);

    // Both terms present
    expect(screen.getByText("noise.com")).toBeInTheDocument();
    expect(screen.getByText("spamword")).toBeInTheDocument();

    // Click first delete button (for TERM_1)
    const deleteButtons = screen.getAllByRole("button", { name: /delete term/i });
    await user.click(deleteButtons[0]);

    await waitFor(() => {
      expect(vi.mocked(toast.success)).toHaveBeenCalledWith(
        "Term removed from stoplist.",
      );
    });

    // TERM_1 row removed from DOM
    expect(screen.queryByText("noise.com")).not.toBeInTheDocument();
    // TERM_2 still present
    expect(screen.getByText("spamword")).toBeInTheDocument();
  });
});
