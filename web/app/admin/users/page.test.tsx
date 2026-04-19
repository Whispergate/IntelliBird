/**
 * AdminUsersPage — activated in plan 09-08.
 *
 * Tests use React Testing Library + vitest. Fetch is mocked globally via
 * vi.stubGlobal so each test controls the API response.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AdminUsersPage from "./page";
import { AddUserDialog } from "./AddUserDialog";
import { ConfirmDialog } from "./ConfirmDialog";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeUser(overrides: Partial<{
  id: string;
  username: string;
  role: "Admin" | "Analyst" | "Viewer";
  dashboard_roles: string[];
  enabled: boolean;
  must_change_password: boolean;
  locked: boolean;
  last_login_at: string | null;
  created_at: string;
}> = {}) {
  return {
    id: "user-1",
    username: "alice",
    role: "Admin" as const,
    dashboard_roles: ["red", "blue"],
    enabled: true,
    must_change_password: false,
    locked: false,
    last_login_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function mockFetch(users: ReturnType<typeof makeUser>[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => users,
      status: 200,
    }),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdminUsersPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders 6-column table with Username/Role/Dashboards/Status/Last login/Actions", async () => {
    mockFetch([makeUser()]);
    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText("Username")).toBeTruthy();
      expect(screen.getByText("Role")).toBeTruthy();
      expect(screen.getByText("Dashboards")).toBeTruthy();
      expect(screen.getByText("Status")).toBeTruthy();
      expect(screen.getByText("Last login")).toBeTruthy();
      expect(screen.getByText("Actions")).toBeTruthy();
    });
  });

  it("empty state shows 'No users' / 'Create the first admin account via /setup.'", async () => {
    mockFetch([]);
    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText("No users")).toBeTruthy();
      expect(
        screen.getByText("Create the first admin account via /setup."),
      ).toBeTruthy();
    });
  });

  it("'Add user' button is rendered at top-right", async () => {
    mockFetch([]);
    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText("Add user")).toBeTruthy();
    });
  });

  it("Disabled row renders opacity-40 italic", async () => {
    mockFetch([makeUser({ enabled: false, username: "disabled-bob" })]);
    render(<AdminUsersPage />);
    await waitFor(() => {
      const row = screen.getByText("disabled-bob").closest("tr");
      expect(row?.className).toContain("opacity-40");
      expect(row?.className).toContain("italic");
    });
  });

  it("Locked user row shows 'Locked' badge and Unlock button", async () => {
    mockFetch([makeUser({ locked: true, username: "locked-carol" })]);
    render(<AdminUsersPage />);
    await waitFor(() => {
      expect(screen.getByText("Locked")).toBeTruthy();
      expect(screen.getByLabelText("Unlock account")).toBeTruthy();
    });
  });

  it("Unlock confirmation dialog renders 'Keep locked' dismiss button", async () => {
    render(
      <ConfirmDialog
        open={true}
        title="Unlock account"
        body="Clear the failed-attempt counter for alice? The user will be able to sign in immediately."
        confirmLabel="Unlock account"
        confirmVariant="default"
        dismissLabel="Keep locked"
        onConfirm={async () => {}}
        onOpenChange={() => {}}
      />,
    );
    expect(screen.getByText("Keep locked")).toBeTruthy();
    // heading and confirm button both say "Unlock account" — confirm is a <button>
    expect(screen.getByRole("button", { name: "Unlock account" })).toBeTruthy();
    expect(
      screen.getByText(/Clear the failed-attempt counter for alice/),
    ).toBeTruthy();
  });

  it("Disable confirmation uses destructive variant and 'Keep active' dismiss", async () => {
    render(
      <ConfirmDialog
        open={true}
        title="Disable user"
        body="Disable alice? They will be signed out of all active sessions immediately and cannot sign in until re-enabled."
        confirmLabel="Disable user"
        confirmVariant="destructive"
        dismissLabel="Keep active"
        onConfirm={async () => {}}
        onOpenChange={() => {}}
      />,
    );
    expect(screen.getByText("Keep active")).toBeTruthy();
    const confirmBtn = screen.getByRole("button", { name: "Disable user" });
    // Destructive variant applies bg-destructive class
    expect(confirmBtn.className).toContain("destructive");
  });

  it("Re-enable confirmation has 'Keep disabled' dismiss and default variant CTA", async () => {
    render(
      <ConfirmDialog
        open={true}
        title="Re-enable user"
        body="Re-enable alice? They will be able to sign in immediately."
        confirmLabel="Re-enable user"
        confirmVariant="default"
        dismissLabel="Keep disabled"
        onConfirm={async () => {}}
        onOpenChange={() => {}}
      />,
    );
    expect(screen.getByText("Keep disabled")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Re-enable user" })).toBeTruthy();
  });
});

describe("AddUserDialog", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("Admin role auto-checks both Red + Blue dashboard checkboxes and disables them", async () => {
    render(
      <AddUserDialog open={true} onOpenChange={() => {}} onCreated={() => {}} />,
    );

    // Initial role is Viewer — checkboxes unchecked and enabled
    const redCheckbox = screen.getByRole("checkbox", { name: /red/i });
    const blueCheckbox = screen.getByRole("checkbox", { name: /blue/i });
    expect(redCheckbox).not.toBeChecked();
    expect(blueCheckbox).not.toBeChecked();
    expect(redCheckbox).not.toBeDisabled();
    expect(blueCheckbox).not.toBeDisabled();

    // Switch role to Admin via select trigger + item
    const trigger = screen.getByRole("combobox");
    fireEvent.click(trigger);
    await waitFor(() => screen.getByRole("option", { name: "Admin" }));
    fireEvent.click(screen.getByRole("option", { name: "Admin" }));

    // After selecting Admin, checkboxes should be checked and disabled
    await waitFor(() => {
      const redAfter = screen.getByRole("checkbox", { name: /red/i });
      const blueAfter = screen.getByRole("checkbox", { name: /blue/i });
      expect(redAfter).toBeChecked();
      expect(blueAfter).toBeChecked();
      expect(redAfter).toBeDisabled();
      expect(blueAfter).toBeDisabled();
    });
  });

  it("password length counter reflects input length", async () => {
    render(
      <AddUserDialog open={true} onOpenChange={() => {}} onCreated={() => {}} />,
    );
    expect(screen.getByText("0 / 12 characters")).toBeTruthy();

    const passwordInput = screen.getByLabelText("Initial password");
    fireEvent.change(passwordInput, { target: { value: "short" } });
    expect(screen.getByText("5 / 12 characters")).toBeTruthy();
  });

  it("'Create user' button is rendered as CTA and 'Discard user' as dismiss", async () => {
    render(
      <AddUserDialog open={true} onOpenChange={() => {}} onCreated={() => {}} />,
    );
    expect(screen.getByText("Create user")).toBeTruthy();
    expect(screen.getByText("Discard user")).toBeTruthy();
  });

  it("shows 'Username already exists.' on 409 response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => ({ detail: "Username already exists" }),
      }),
    );

    render(
      <AddUserDialog open={true} onOpenChange={() => {}} onCreated={() => {}} />,
    );

    // Fill all required fields with valid data
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "duplicate-user" },
    });
    fireEvent.change(screen.getByLabelText("Initial password"), {
      target: { value: "validpassword123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "validpassword123" },
    });

    // Check at least one dashboard for Viewer role
    const redCheckbox = screen.getByRole("checkbox", { name: /red/i });
    fireEvent.click(redCheckbox);

    // Submit
    fireEvent.click(screen.getByText("Create user"));

    await waitFor(() => {
      expect(screen.getByText("Username already exists.")).toBeTruthy();
    });
  });
});
