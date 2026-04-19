/**
 * Change-password page tests — AUTH-01.
 *
 * Forced redirect on must_change_password; password length counter; error states.
 * Activated in plan 09-07.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockPush = vi.fn();
const mockGet = vi.fn().mockReturnValue(null);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({
    get: mockGet,
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}));

import ChangePasswordPage from "@/app/(auth)/change-password/page";
import { toast } from "sonner";

describe("ChangePasswordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockReturnValue(null);
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ dashboard_roles: ["red"] }),
    });
  });

  it("renders first_login guidance copy when ?reason=first_login", () => {
    mockGet.mockImplementation((key: string) => {
      if (key === "reason") return "first_login";
      return null;
    });
    render(<ChangePasswordPage />);
    expect(
      screen.getByText(
        "You must set a new password before continuing. Your initial password was set by an admin."
      )
    ).toBeDefined();
  });

  it("renders standard copy when no reason param", () => {
    mockGet.mockReturnValue(null);
    render(<ChangePasswordPage />);
    expect(screen.getByText("Change your password.")).toBeDefined();
  });

  it("shows Incorrect password on 401", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: "invalid_credentials" }),
    });
    render(<ChangePasswordPage />);

    await userEvent.type(screen.getByLabelText("Current password"), "wrongpass123456");
    await userEvent.type(screen.getByLabelText("New password"), "newpassword123456");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "newpassword123456");
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    await waitFor(() => {
      expect(screen.getByText("Incorrect password.")).toBeDefined();
    });
  });

  it("shows New password must differ on 400 new_password_same_as_current", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ detail: "new_password_same_as_current" }),
    });
    render(<ChangePasswordPage />);

    await userEvent.type(screen.getByLabelText("Current password"), "samepassword123");
    await userEvent.type(screen.getByLabelText("New password"), "samepassword123");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "samepassword123");
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    await waitFor(() => {
      expect(
        screen.getByText("New password must differ from your current password.")
      ).toBeDefined();
    });
  });

  it("password length counter on new-password field", async () => {
    render(<ChangePasswordPage />);
    const newPwdInput = screen.getByLabelText("New password");

    await userEvent.type(newPwdInput, "short");
    await waitFor(() => {
      expect(screen.getByText(/5 \/ 12 characters/)).toBeDefined();
    });

    await userEvent.clear(newPwdInput);
    await userEvent.type(newPwdInput, "longpassword12");
    await waitFor(() => {
      expect(screen.getByText(/14 \/ 12 characters/)).toBeDefined();
    });
  });

  it("fires success toast and redirects on success", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ dashboard_roles: ["red"] }),
      });

    render(<ChangePasswordPage />);

    await userEvent.type(screen.getByLabelText("Current password"), "oldpassword123");
    await userEvent.type(screen.getByLabelText("New password"), "newpassword456");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "newpassword456");
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Password updated", { duration: 3000 });
      expect(mockPush).toHaveBeenCalledWith("/red");
    });
  });
});
