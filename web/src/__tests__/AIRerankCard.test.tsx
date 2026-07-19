// Owned by: 17-09-PLAN
// AIRerankCard - Surface 5 per 17-UI-SPEC.md.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { AIRerankCard } from "@/app/projects/[id]/scoring/AIRerankCard";
import { toast } from "sonner";

const toastSuccess = vi.mocked(toast.success);
const toastError = vi.mocked(toast.error);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.resetAllMocks();
  globalThis.fetch = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AIRerankCard (17-09)", () => {
  describe("render gate", () => {
    it("renders nothing when aiRerankEnabled=false", () => {
      const { container } = render(
        <AIRerankCard projectId="p1" aiRerankEnabled={false} />,
      );
      expect(container.firstChild).toBeNull();
    });

    it("renders card when aiRerankEnabled=true", async () => {
      vi.mocked(fetch).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ last_rerank_at: null, in_progress_count: 0, total_count: 0 }),
      } as Response);
      render(<AIRerankCard projectId="p1" aiRerankEnabled={true} />);
      await waitFor(() => {
        expect(screen.getByText("AI Re-ranking")).toBeTruthy();
      });
    });
  });

  describe("Re-rerank now button", () => {
    it("shows 'Re-rerank now' button", async () => {
      vi.mocked(fetch).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ last_rerank_at: null, in_progress_count: 0, total_count: 0 }),
      } as Response);
      render(<AIRerankCard projectId="p1" aiRerankEnabled={true} />);
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Re-rerank now/i })).toBeTruthy();
      });
    });
  });

  describe("polling lifecycle", () => {
    it("on Re-rerank now: POST fires + toast.success('AI re-ranking queued.')", async () => {
      vi.mocked(fetch)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ last_rerank_at: null, in_progress_count: 0, total_count: 0 }),
        } as Response)
        .mockResolvedValue({
          ok: true,
          status: 202,
          json: async () => ({ queued: true }),
        } as Response);

      render(<AIRerankCard projectId="p1" aiRerankEnabled={true} />);
      await waitFor(() => screen.getByRole("button", { name: /Re-rerank now/i }));

      await act(async () => {
        await userEvent.click(screen.getByRole("button", { name: /Re-rerank now/i }));
      });

      expect(toastSuccess).toHaveBeenCalledWith("AI re-ranking queued.");
    });

    it("polling complete: when in_progress→0 fires complete toast", async () => {
      // Use fake timers with shouldAdvanceTime so waitFor still works
      vi.useFakeTimers({ shouldAdvanceTime: true });

      vi.mocked(fetch)
        .mockResolvedValueOnce({
          // Initial status load
          ok: true,
          status: 200,
          json: async () => ({ last_rerank_at: null, in_progress_count: 0, total_count: 0 }),
        } as Response)
        .mockResolvedValueOnce({
          // POST ai-rescore
          ok: true,
          status: 202,
          json: async () => ({ queued: true }),
        } as Response)
        .mockResolvedValueOnce({
          // Poll tick 1: in progress
          ok: true,
          status: 200,
          json: async () => ({ last_rerank_at: null, in_progress_count: 5, total_count: 10 }),
        } as Response)
        .mockResolvedValueOnce({
          // Poll tick 2: complete
          ok: true,
          status: 200,
          json: async () => ({
            last_rerank_at: new Date().toISOString(),
            in_progress_count: 0,
            total_count: 10,
          }),
        } as Response);

      render(<AIRerankCard projectId="p1" aiRerankEnabled={true} />);
      await waitFor(() => screen.getByRole("button", { name: /Re-rerank now/i }));

      await act(async () => {
        await userEvent.click(screen.getByRole("button", { name: /Re-rerank now/i }));
      });

      expect(toastSuccess).toHaveBeenCalledWith("AI re-ranking queued.");

      // Advance timers past first poll interval
      await act(async () => {
        vi.advanceTimersByTime(3100);
        await Promise.resolve();
        await Promise.resolve();
      });

      // Advance past second poll interval to trigger complete
      await act(async () => {
        vi.advanceTimersByTime(3100);
        await Promise.resolve();
        await Promise.resolve();
      });

      await waitFor(() => {
        expect(toastSuccess).toHaveBeenCalledWith(
          "AI re-ranking complete - 10 events updated.",
        );
      });
    });

    it("poll HTTP error: stops polling and fires error toast", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });

      vi.mocked(fetch)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ last_rerank_at: null, in_progress_count: 0, total_count: 0 }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 202,
          json: async () => ({}),
        } as Response)
        .mockResolvedValueOnce({
          ok: false,
          status: 500,
          json: async () => ({}),
          text: async () => "Server error",
        } as Response);

      render(<AIRerankCard projectId="p1" aiRerankEnabled={true} />);
      await waitFor(() => screen.getByRole("button", { name: /Re-rerank now/i }));

      await act(async () => {
        await userEvent.click(screen.getByRole("button", { name: /Re-rerank now/i }));
      });

      await act(async () => {
        vi.advanceTimersByTime(3100);
        await Promise.resolve();
        await Promise.resolve();
      });

      await waitFor(() => {
        expect(toastError).toHaveBeenCalledWith("Re-ranking status check failed.");
      });
    });
  });

  describe("cleanup", () => {
    it("unmount clears interval (no leaked timers)", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval");

      vi.mocked(fetch)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ last_rerank_at: null, in_progress_count: 0, total_count: 0 }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 202,
          json: async () => ({}),
        } as Response)
        .mockResolvedValue({
          ok: true,
          status: 200,
          json: async () => ({ last_rerank_at: null, in_progress_count: 1, total_count: 5 }),
        } as Response);

      const { unmount } = render(
        <AIRerankCard projectId="p1" aiRerankEnabled={true} />,
      );
      await waitFor(() => screen.getByRole("button", { name: /Re-rerank now/i }));

      await act(async () => {
        await userEvent.click(screen.getByRole("button", { name: /Re-rerank now/i }));
      });

      unmount();
      expect(clearIntervalSpy).toHaveBeenCalled();
      clearIntervalSpy.mockRestore();
    });
  });
});
