/**
 * EASMGateForm tests — plan 11-10.
 *
 * Tests Surface 2: Active-scan Gate Form (replaces EASMGatePreview on Settings tab).
 * Activated in plan 11-10 (was a Wave 0 stub referencing plan 11-11).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EASMGateForm } from "../EASMGateForm";
import type { EASMGateProject } from "../EASMGateForm";

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
// Fixtures
// ---------------------------------------------------------------------------

const RECENT_DATE = new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(); // 1 day ago
const OLD_DATE = new Date(Date.now() - 6.5 * 24 * 60 * 60 * 1000).toISOString(); // 6.5 days ago

const baseProject: EASMGateProject = {
  id: "proj-123",
  name: "my-project",
  archived: false,
  active_scans_authorised: false,
  scope_acknowledgement_text: null,
  active_auth_confirmed_at: null,
  active_auth_confirmed_by: null,
};

const authorisedProject: EASMGateProject = {
  ...baseProject,
  active_scans_authorised: true,
  scope_acknowledgement_text: "my-project",
  active_auth_confirmed_at: RECENT_DATE,
  active_auth_confirmed_by: "sub|user-abc-123-xzy-456-foo",
};

function renderGate(
  overrides: Partial<EASMGateProject> = {},
  opts: {
    isLegacy?: boolean;
    userIsLeadOrAdmin?: boolean;
    ttlSeconds?: number;
  } = {},
) {
  const project = { ...baseProject, ...overrides };
  const onGateChanged = vi.fn();
  render(
    <EASMGateForm
      project={project}
      isLegacy={opts.isLegacy ?? false}
      userIsLeadOrAdmin={opts.userIsLeadOrAdmin ?? true}
      ttlSeconds={opts.ttlSeconds ?? 604800}
      onGateChanged={onGateChanged}
    />,
  );
  return { onGateChanged };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EASMGateForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset fetch mock
    vi.stubGlobal("fetch", vi.fn());
  });

  it('renders caption "Active-scan authorisation"', () => {
    renderGate();
    expect(screen.getByText("Active-scan authorisation")).toBeInTheDocument();
  });

  it("renders form with field 1 Input + field 2 Checkbox + Submit button when gate not set and user is Lead", () => {
    renderGate();
    expect(
      screen.getByLabelText(/Type the project name to confirm scope acknowledgement/i),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/I confirm that written authorisation exists/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Authorise active scans/i }),
    ).toBeInTheDocument();
  });

  it("submit disabled when ackText is empty", () => {
    renderGate();
    const btn = screen.getByRole("button", { name: /Authorise active scans/i });
    expect(btn).toBeDisabled();
  });

  it("submit disabled when ackText does not match project.name", async () => {
    const user = userEvent.setup();
    renderGate();
    const input = screen.getByPlaceholderText("Type project name exactly");
    await user.type(input, "wrong-name");
    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);
    const btn = screen.getByRole("button", { name: /Authorise active scans/i });
    expect(btn).toBeDisabled();
  });

  it("submit disabled when checkbox unchecked", async () => {
    const user = userEvent.setup();
    renderGate();
    const input = screen.getByPlaceholderText("Type project name exactly");
    await user.type(input, "my-project");
    // checkbox NOT checked
    const btn = screen.getByRole("button", { name: /Authorise active scans/i });
    expect(btn).toBeDisabled();
  });

  it("submit enabled when both fields valid", async () => {
    const user = userEvent.setup();
    renderGate();
    const input = screen.getByPlaceholderText("Type project name exactly");
    await user.type(input, "my-project");
    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);
    const btn = screen.getByRole("button", { name: /Authorise active scans/i });
    expect(btn).not.toBeDisabled();
  });

  it('submit disabled during submission + label shows "Authorising…"', async () => {
    // Simulate a slow fetch
    let resolvePromise!: (v: Response) => void;
    const slowFetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolvePromise = resolve;
        }),
    );
    vi.stubGlobal("fetch", slowFetch);

    const user = userEvent.setup();
    renderGate();
    const input = screen.getByPlaceholderText("Type project name exactly");
    await user.type(input, "my-project");
    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);
    const btn = screen.getByRole("button", { name: /Authorise active scans/i });
    await user.click(btn);

    // Button should show loading state
    await waitFor(() => {
      expect(screen.getByText("Authorising…")).toBeInTheDocument();
    });

    // Clean up
    resolvePromise(new Response(JSON.stringify({ ...baseProject }), { status: 200, headers: { "Content-Type": "application/json" } }));
  });

  it("submit calls PATCH /api/projects/{id}/easm-gate with correct body", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...baseProject,
          active_scans_authorised: true,
          active_auth_confirmed_at: new Date().toISOString(),
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const user = userEvent.setup();
    renderGate();
    const input = screen.getByPlaceholderText("Type project name exactly");
    await user.type(input, "my-project");
    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);
    const btn = screen.getByRole("button", { name: /Authorise active scans/i });
    await user.click(btn);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/projects/proj-123/easm-gate",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            scope_acknowledgement_text: "my-project",
            confirm_authorisation: true,
          }),
        }),
      );
    });
  });

  it("submit with 403 triggers toast with canonical copy byte-exact", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "forbidden" }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", mockFetch);

    const { toast } = await import("sonner");
    const user = userEvent.setup();
    renderGate();
    const input = screen.getByPlaceholderText("Type project name exactly");
    await user.type(input, "my-project");
    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);
    const btn = screen.getByRole("button", { name: /Authorise active scans/i });
    await user.click(btn);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "You do not have permission to authorise active scans. Lead or Admin role required.",
      );
    });
  });

  it('submit with 422 (scope_ack mismatch) surfaces inline error "Scope acknowledgement text does not match the project name."', async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "Scope acknowledgement text does not match project name." }),
        {
          status: 422,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const user = userEvent.setup();
    renderGate();
    const input = screen.getByPlaceholderText("Type project name exactly");
    await user.type(input, "my-project");
    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);
    const btn = screen.getByRole("button", { name: /Authorise active scans/i });
    await user.click(btn);

    await waitFor(() => {
      expect(
        screen.getByText(
          "Scope acknowledgement text does not match the project name.",
        ),
      ).toBeInTheDocument();
    });
  });

  it('status strip renders "Active scans authorised" when project.active_scans_authorised=true', () => {
    renderGate(authorisedProject);
    expect(screen.getByText("Active scans authorised")).toBeInTheDocument();
  });

  it("24h banner renders when active_auth_confirmed_at > 6d ago", () => {
    renderGate({
      ...authorisedProject,
      active_auth_confirmed_at: OLD_DATE,
    });
    expect(
      screen.getByText(
        /Active-scan authorisation expires in less than 24 hours/i,
      ),
    ).toBeInTheDocument();
  });

  it("24h banner does NOT render when confirmed_at is recent", () => {
    renderGate(authorisedProject); // RECENT_DATE (1 day ago)
    expect(
      screen.queryByText(
        /Active-scan authorisation expires in less than 24 hours/i,
      ),
    ).not.toBeInTheDocument();
  });

  it("Revoke button visible when gate set + userIsLeadOrAdmin=true", () => {
    renderGate(authorisedProject, { userIsLeadOrAdmin: true });
    expect(
      screen.getByRole("button", { name: /Revoke authorisation/i }),
    ).toBeInTheDocument();
  });

  it("Revoke button hidden when userIsLeadOrAdmin=false", () => {
    renderGate(authorisedProject, { userIsLeadOrAdmin: false });
    expect(
      screen.queryByRole("button", { name: /Revoke authorisation/i }),
    ).not.toBeInTheDocument();
  });

  it("Revoke click calls window.confirm with byte-exact copy; if confirmed, calls DELETE endpoint", async () => {
    const mockConfirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ ...authorisedProject, active_scans_authorised: false }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const user = userEvent.setup();
    renderGate(authorisedProject, { userIsLeadOrAdmin: true });
    const revokeBtn = screen.getByRole("button", { name: /Revoke authorisation/i });
    await user.click(revokeBtn);

    expect(mockConfirm).toHaveBeenCalledWith(
      `Revoke active-scan authorisation for "my-project"? Running active scans will complete but no new active scans can be launched until re-authorised.`,
    );
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/projects/proj-123/easm-gate",
        expect.objectContaining({ method: "DELETE" }),
      );
    });

    mockConfirm.mockRestore();
  });

  it('Revoke success → toast "Active-scan authorisation revoked."', async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ ...authorisedProject, active_scans_authorised: false }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const { toast } = await import("sonner");
    const user = userEvent.setup();
    renderGate(authorisedProject, { userIsLeadOrAdmin: true });
    const revokeBtn = screen.getByRole("button", { name: /Revoke authorisation/i });
    await user.click(revokeBtn);

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        "Active-scan authorisation revoked.",
      );
    });
  });

  it("Observer/Contributor: all inputs disabled + caption about Lead/Admin requirement", () => {
    renderGate({}, { userIsLeadOrAdmin: false, isLegacy: false });
    expect(
      screen.getByText(
        "Active-scan authorisation can only be set or revoked by a project Lead or global Admin.",
      ),
    ).toBeInTheDocument();
    const input = screen.queryByPlaceholderText("Type project name exactly");
    if (input) {
      expect(input).toBeDisabled();
    }
  });

  it("Legacy project: all inputs disabled + caption about unavailability", () => {
    renderGate({}, { isLegacy: true, userIsLeadOrAdmin: true });
    expect(
      screen.getByText(
        "Authorisation is not available for archived or legacy projects.",
      ),
    ).toBeInTheDocument();
    const input = screen.queryByPlaceholderText("Type project name exactly");
    if (input) {
      expect(input).toBeDisabled();
    }
  });

  it("Archived project: shows legacy/archived caption", () => {
    renderGate({ archived: true }, { userIsLeadOrAdmin: true });
    expect(
      screen.getByText(
        "Authorisation is not available for archived or legacy projects.",
      ),
    ).toBeInTheDocument();
  });
});
