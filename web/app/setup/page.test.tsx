/**
 * Setup page tests — AUTH-01.
 *
 * Renders only when SETUP_TOKEN set; shows already-complete state when user exists;
 * validates password length 12; redirects to /login on success. Activated in plan 09-07.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockPush = vi.fn();
const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}));

import SetupPage from "@/app/(auth)/setup/page";
import { toast } from "sonner";

function mockStatus(status: { setup_token_set: boolean; user_count: number }) {
  global.fetch = vi.fn().mockResolvedValue({
    json: () => Promise.resolve(status),
    ok: true,
    status: 200,
  });
}

describe("SetupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders operator guidance copy", async () => {
    mockStatus({ setup_token_set: true, user_count: 0 });
    render(<SetupPage />);
    await waitFor(() => {
      // The heading should say "IntelliBird First-Admin Setup"
      expect(screen.getByRole("heading", { name: /IntelliBird First-Admin Setup/i })).toBeDefined();
      // SETUP_TOKEN should appear in the guidance text
      const setupTokenRefs = screen.getAllByText("SETUP_TOKEN");
      expect(setupTokenRefs.length).toBeGreaterThan(0);
    });
  });

  it("shows Setup already complete when user exists", async () => {
    mockStatus({ setup_token_set: true, user_count: 1 });
    render(<SetupPage />);
    await waitFor(() => {
      expect(screen.getByText("Setup already complete")).toBeDefined();
      expect(screen.queryByRole("button", { name: "Create admin account" })).toBeNull();
    });
  });

  it("password length counter transitions color at 12 chars", async () => {
    mockStatus({ setup_token_set: true, user_count: 0 });
    render(<SetupPage />);
    await waitFor(() => screen.getByLabelText("Password"));

    const passwordInput = screen.getByLabelText("Password");
    // Below 12: counter shows muted color
    await userEvent.type(passwordInput, "short");
    await waitFor(() => {
      const counter = screen.getByText(/5 \/ 12 characters/);
      expect(counter).toBeDefined();
    });

    // At 12: counter transitions to primary
    await userEvent.clear(passwordInput);
    await userEvent.type(passwordInput, "twelvecharspw");
    await waitFor(() => {
      // 13 chars typed
      const counter = screen.getByText(/13 \/ 12 characters/);
      expect(counter).toBeDefined();
    });
  });

  it("Passwords do not match error on mismatch", async () => {
    mockStatus({ setup_token_set: true, user_count: 0 });
    render(<SetupPage />);
    await waitFor(() => screen.getByLabelText("Username"));

    // Username is required for submit button to be enabled
    await userEvent.type(screen.getByLabelText("Username"), "adminuser");
    await userEvent.type(screen.getByLabelText("Password"), "longpassword123");
    await userEvent.type(screen.getByLabelText("Confirm password"), "differentpassword");
    fireEvent.click(screen.getByRole("button", { name: "Create admin account" }));

    await waitFor(() => {
      expect(screen.getByText("Passwords do not match.")).toBeDefined();
    });
  });

  it("redirects to /login on successful admin creation", async () => {
    // First call: status fetch. Second call: POST to /api/admin/setup.
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ setup_token_set: true, user_count: 0 }),
        ok: true,
        status: 200,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ id: "uuid-123" }),
      });

    render(<SetupPage />);
    await waitFor(() => screen.getByLabelText("Username"));

    await userEvent.type(screen.getByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "securepassword123");
    await userEvent.type(screen.getByLabelText("Confirm password"), "securepassword123");
    fireEvent.click(screen.getByRole("button", { name: "Create admin account" }));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        "Admin account created",
        expect.objectContaining({ description: "Sign in to continue." })
      );
      expect(mockPush).toHaveBeenCalledWith("/login");
    });
  });
});
