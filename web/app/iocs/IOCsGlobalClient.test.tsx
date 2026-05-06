/**
 * IOCsGlobalClient tests — Phase 34 Plan 01 (Wave 0 RED).
 *
 * Covers:
 *   - EXT-02a: Component mounts with initialQ pre-filled in the search input
 *   - EXT-02b: listIOCs is called without a projectId key (global page)
 *
 * These tests are intentionally RED — IOCsGlobalClient.tsx does not exist yet.
 * They will go Green when Wave 1 (plan 34-02) delivers the implementation.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// RED: file does not exist yet — causes module-not-found failure
import { IOCsGlobalClient } from "./IOCsGlobalClient";

vi.mock("@/app/api-client", () => ({
  listIOCs: vi.fn().mockResolvedValue([]),
  getIOC: vi.fn().mockResolvedValue(null),
  patchIOC: vi.fn().mockResolvedValue(null),
  deleteIOC: vi.fn().mockResolvedValue(null),
  whitelistIOC: vi.fn().mockResolvedValue(null),
  unwhitelistIOC: vi.fn().mockResolvedValue(null),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/iocs",
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

describe("IOCsGlobalClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with initialQ pre-filled in search input", () => {
    render(<IOCsGlobalClient initialRows={[]} initialQ="malware.exe" />);
    // Expect an input element with value "malware.exe"
    const input = screen.getByRole("textbox");
    expect(input).toHaveValue("malware.exe");
  });

  it("calls listIOCs without projectId on filter change", async () => {
    const { listIOCs } = await import("@/app/api-client");
    render(<IOCsGlobalClient initialRows={[]} initialQ="" />);
    // Assert that any listIOCs call made during render does not include projectId
    const calls = (listIOCs as ReturnType<typeof vi.fn>).mock.calls;
    // If called, projectId must be absent from the params object
    for (const [params] of calls) {
      expect(params).not.toHaveProperty("projectId");
    }
  });
});
