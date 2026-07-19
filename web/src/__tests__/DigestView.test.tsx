// Owned by: 17-09-PLAN
// DigestView - Surface 3 per 17-UI-SPEC.md.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(),
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { DigestView } from "@/app/projects/[id]/digest/DigestView";
import { useSession } from "next-auth/react";
import { toast } from "sonner";

const useSessionMock = vi.mocked(useSession);
const toastSuccess = vi.mocked(toast.success);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function adminSession() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  useSessionMock.mockReturnValue({
    data: { user: { role: "Admin" }, expires: "" },
    status: "authenticated",
    update: vi.fn(),
  } as any);
}

function analystSession() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  useSessionMock.mockReturnValue({
    data: { user: { role: "Analyst" }, expires: "" },
    status: "authenticated",
    update: vi.fn(),
  } as any);
}

const mockDigest = {
  id: "d1",
  project_id: "p1",
  summary_type: "digest",
  provider_used: "ollama",
  model_used: "phi3:mini",
  prompt_template_version: "DIGEST_PROMPT_V1",
  summary_text:
    "## Highlights\n- Critical CVE found\n- Threat actor active\n- Summary based on 5 of 10 events",
  tokens_used: 500,
  requires_analyst_review: false,
  created_at: new Date(Date.now() - 60_000).toISOString(),
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.resetAllMocks();
  globalThis.fetch = vi.fn();
});

describe("DigestView (17-09)", () => {
  describe("markdown-lite rendering", () => {
    it("renders ## heading as <h3>", async () => {
      adminSession();
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockDigest,
      } as Response);

      render(<DigestView projectId="p1" />);
      await waitFor(() => {
        expect(screen.getByRole("heading", { name: "Highlights", level: 3 })).toBeTruthy();
      });
    });

    it("renders - bullet as <li>", async () => {
      adminSession();
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockDigest,
      } as Response);

      render(<DigestView projectId="p1" />);
      await waitFor(() => {
        expect(screen.getByText("Critical CVE found")).toBeTruthy();
      });
      const item = screen.getByText("Critical CVE found").closest("li");
      expect(item).toBeTruthy();
    });

    it("renders truncation footer as separate paragraph", async () => {
      adminSession();
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockDigest,
      } as Response);

      render(<DigestView projectId="p1" />);
      await waitFor(() => {
        expect(screen.getByText("- Summary based on 5 of 10 events")).toBeTruthy();
      });
      const el = screen.getByText("- Summary based on 5 of 10 events");
      expect(el.tagName.toLowerCase()).toBe("p");
    });
  });

  describe("empty state", () => {
    it("renders FileText icon area + exact UI-SPEC copy when no digest", async () => {
      adminSession();
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ detail: "Not found" }),
        text: async () => "Not found",
      } as Response);

      render(<DigestView projectId="p1" />);
      await waitFor(() => {
        expect(screen.getByText("No digest generated yet")).toBeTruthy();
      });
      expect(
        screen.getByText(/Digests run automatically at 06:00 UTC/),
      ).toBeTruthy();
    });
  });

  describe("Generate now button", () => {
    it("admin sees Generate now button", async () => {
      adminSession();
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({}),
        text: async () => "",
      } as Response);

      render(<DigestView projectId="p1" />);
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Generate now/i })).toBeTruthy();
      });
    });

    it("analyst does not see Generate now button", async () => {
      analystSession();
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({}),
        text: async () => "",
      } as Response);

      render(<DigestView projectId="p1" />);
      await waitFor(() => {
        expect(screen.getByText("No digest generated yet")).toBeTruthy();
      });
      expect(screen.queryByRole("button", { name: /Generate now/i })).toBeNull();
    });

    it("on Generate now: button disabled + toast.success('Digest generation queued.')", async () => {
      adminSession();
      // First fetch (load digest) → 404
      // Second fetch (generate) → 200
      vi.mocked(fetch)
        .mockResolvedValueOnce({
          ok: false,
          status: 404,
          json: async () => ({}),
          text: async () => "",
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 202,
          json: async () => ({}),
        } as Response);

      render(<DigestView projectId="p1" />);
      await waitFor(() => screen.getByRole("button", { name: /Generate now/i }));

      const btn = screen.getByRole("button", { name: /Generate now/i });
      await act(async () => {
        await userEvent.click(btn);
      });

      expect(toastSuccess).toHaveBeenCalledWith("Digest generation queued.");
      // Button should be disabled after click (10s debounce)
      expect(btn).toBeDisabled();
    });
  });
});
