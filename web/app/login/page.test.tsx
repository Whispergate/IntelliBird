/**
 * Login page tests — AUTH-04.
 *
 * Renders login form, disables submit until valid, shows 429 lockout, surfaces
 * "Invalid username or password" on 401. Activated in plan 09-07.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock next-auth/react signIn
vi.mock("next-auth/react", () => ({
  signIn: vi.fn(),
}));

// Mock next/navigation
const mockPush = vi.fn();
const mockGet = vi.fn().mockReturnValue(null);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({
    get: mockGet,
  }),
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
  },
}));

import LoginPage from "@/app/(auth)/login/page";
import { signIn } from "next-auth/react";
import { toast } from "sonner";

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: no reason param, no SSO
    mockGet.mockReturnValue(null);
    global.fetch = vi.fn().mockResolvedValue({
      json: () => Promise.resolve({ sso_enabled: false }),
      ok: true,
    });
  });

  it("renders Sign in heading", () => {
    render(<LoginPage />);
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeDefined();
  });

  it("disables Sign in button when fields empty", () => {
    render(<LoginPage />);
    const btn = screen.getByRole("button", { name: "Sign in" });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows Invalid username or password on 401", async () => {
    (signIn as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ error: "CredentialsSignin" });
    render(<LoginPage />);

    await userEvent.type(screen.getByLabelText("Username"), "baduser");
    await userEvent.type(screen.getByLabelText("Password"), "badpass");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
      expect(screen.getByText("Invalid username or password.")).toBeDefined();
    });
  });

  it("shows lockout message with retry minutes on 429", async () => {
    // 1800 seconds = 30 minutes
    (signIn as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ error: "lockout:1800" });
    render(<LoginPage />);

    await userEvent.type(screen.getByLabelText("Username"), "lockeduser");
    await userEvent.type(screen.getByLabelText("Password"), "somepass");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByText("Account temporarily locked. Try again in 30 minutes.")).toBeDefined();
    });
  });

  it("conditionally renders Sign in with Authentik button when SSO_ISSUER_URL set", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      json: () => Promise.resolve({ sso_enabled: true }),
      ok: true,
    });
    render(<LoginPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sign in with Authentik" })).toBeDefined();
    });
  });

  it("fires info toast when reason=logged_out", async () => {
    mockGet.mockImplementation((key: string) => {
      if (key === "reason") return "logged_out";
      return null;
    });
    render(<LoginPage />);
    await waitFor(() => {
      expect(toast.info).toHaveBeenCalledWith("Signed out", { duration: 3000 });
    });
  });

  it("fires warning toast when reason=expired", async () => {
    mockGet.mockImplementation((key: string) => {
      if (key === "reason") return "expired";
      return null;
    });
    render(<LoginPage />);
    await waitFor(() => {
      expect(toast.warning).toHaveBeenCalledWith("Session expired", {
        description: "Sign in again to continue.",
        duration: 4000,
      });
    });
  });

  it("fires error toast when reason=revoked", async () => {
    mockGet.mockImplementation((key: string) => {
      if (key === "reason") return "revoked";
      return null;
    });
    render(<LoginPage />);
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Session revoked", {
        description: "Your session was invalidated for security reasons. Sign in again.",
        duration: 6000,
      });
    });
  });
});
