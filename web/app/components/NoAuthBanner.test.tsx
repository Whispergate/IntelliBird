/**
 * NoAuthBanner tests - AUTH-04.
 *
 * Null render when auth_enabled=true && decrypt_check !== 'failed'.
 * Activated in plan 09-07.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { NoAuthBanner } from "@/app/components/NoAuthBanner";
import type { SystemStatus } from "@/app/api-client";

describe("NoAuthBanner", () => {
  it("renders null when auth_enabled=true and decrypt_check is ok", () => {
    const status: SystemStatus = {
      auth_enabled: true,
      decrypt_check: "ok",
      host: "127.0.0.1",
      host_loopback_only: true,
      version: "0.1.0",
      warning: null,
    };
    const { container } = render(<NoAuthBanner status={status} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders banner when auth_enabled=false", () => {
    const status: SystemStatus = {
      auth_enabled: false,
      decrypt_check: "ok",
      host: "127.0.0.1",
      host_loopback_only: true,
      version: "0.1.0",
      warning: null,
    };
    render(<NoAuthBanner status={status} />);
    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText(/NO AUTHENTICATION CONFIGURED/)).toBeDefined();
  });

  it("renders decrypt failure warning when decrypt_check=failed", () => {
    const status: SystemStatus = {
      auth_enabled: true,
      decrypt_check: "failed",
      host: "127.0.0.1",
      host_loopback_only: true,
      version: "0.1.0",
      warning: null,
    };
    render(<NoAuthBanner status={status} />);
    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText(/CREDENTIAL DECRYPTION FAILURE/)).toBeDefined();
  });
});
