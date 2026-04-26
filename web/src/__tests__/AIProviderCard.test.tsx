// Owned by: 17-09-PLAN
// AIProviderCard — Surface 4 per 17-UI-SPEC.md.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
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

import { AIProviderCard } from "@/app/projects/[id]/settings/AIProviderCard";
import { toast } from "sonner";

const toastSuccess = vi.mocked(toast.success);
const toastError = vi.mocked(toast.error);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.resetAllMocks();
  // Default: no existing config (404)
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 404,
    json: async () => ({}),
    text: async () => "",
  } as Response);
});

describe("AIProviderCard (17-09)", () => {
  // Helper: open the provider select and pick an option
  async function selectProvider(label: string) {
    const trigger = screen.getByRole("combobox");
    fireEvent.click(trigger);
    // Radix Select renders options in a portal in document.body
    const option = await waitFor(() => {
      const items = document.querySelectorAll('[role="option"]');
      const match = Array.from(items).find((el) => el.textContent?.trim() === label);
      if (!match) throw new Error(`Option "${label}" not found`);
      return match;
    });
    fireEvent.click(option);
    await act(async () => { await Promise.resolve(); });
  }

  describe("provider select toggles API key visibility", () => {
    it("Ollama selected → API key field hidden", async () => {
      render(<AIProviderCard projectId="p1" />);
      // wait for initial load attempt
      await waitFor(() => screen.getByLabelText("Provider"));
      // Ollama is default — API key should not be visible
      expect(screen.queryByLabelText("API key")).toBeNull();
    });

    it("OpenAI selected → API key field shown", async () => {
      render(<AIProviderCard projectId="p1" />);
      await waitFor(() => screen.getByLabelText("Provider"));
      await selectProvider("OpenAI");
      expect(screen.getByLabelText("API key")).toBeTruthy();
    });

    it("Anthropic selected → API key field shown", async () => {
      render(<AIProviderCard projectId="p1" />);
      await waitFor(() => screen.getByLabelText("Provider"));
      await selectProvider("Anthropic");
      expect(screen.getByLabelText("API key")).toBeTruthy();
    });
  });

  describe("Ollama health inline alert", () => {
    it("renders slow alert with correct copy when ollamaHealth='slow' and provider=ollama", async () => {
      render(<AIProviderCard projectId="p1" ollamaHealth="slow" />);
      await waitFor(() => screen.getByLabelText("Provider"));
      const alert = screen.getByRole("alert");
      expect(alert.textContent).toContain("phi3:mini or gemma2:2b recommended on CPU-only hosts");
    });

    it("renders down alert with correct copy when ollamaHealth='down' and provider=ollama", async () => {
      render(<AIProviderCard projectId="p1" ollamaHealth="down" />);
      await waitFor(() => screen.getByLabelText("Provider"));
      const alert = screen.getByRole("alert");
      expect(alert.textContent).toContain("Ollama unreachable");
    });

    it("renders no alert when ollamaHealth='healthy'", async () => {
      render(<AIProviderCard projectId="p1" ollamaHealth="healthy" />);
      await waitFor(() => screen.getByLabelText("Provider"));
      expect(screen.queryByRole("alert")).toBeNull();
    });

    it("does not render Ollama alert when provider is OpenAI even if health=slow", async () => {
      render(<AIProviderCard projectId="p1" ollamaHealth="slow" />);
      await waitFor(() => screen.getByLabelText("Provider"));
      await selectProvider("OpenAI");
      expect(screen.queryByRole("alert")).toBeNull();
    });
  });

  describe("Save", () => {
    it("PUT /api/projects/{id}/ai-provider on save → toast.success('AI settings saved.')", async () => {
      // First fetch = 404 (no config), second fetch = successful PUT
      globalThis.fetch = vi.fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 404,
          json: async () => ({}),
          text: async () => "",
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({}),
        } as Response);

      render(<AIProviderCard projectId="p1" />);
      await waitFor(() => screen.getByRole("button", { name: /Save AI settings/i }));

      await act(async () => {
        await userEvent.click(screen.getByRole("button", { name: /Save AI settings/i }));
      });

      await waitFor(() => {
        expect(toastSuccess).toHaveBeenCalledWith("AI settings saved.");
      });

      // Verify PUT was called with correct path
      const calls = vi.mocked(fetch).mock.calls;
      const putCall = calls.find((c) => (c[1] as RequestInit)?.method === "PUT");
      expect(putCall?.[0]).toContain("/ai-provider");
    });
  });

  describe("Test connection", () => {
    it("POST /api/projects/{id}/ai-provider/test → toast.success('Connection successful.') on 200", async () => {
      globalThis.fetch = vi.fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 404,
          json: async () => ({}),
          text: async () => "",
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ ok: true, latency_ms: 120 }),
        } as Response);

      render(<AIProviderCard projectId="p1" />);
      await waitFor(() => screen.getByRole("button", { name: /Test connection/i }));

      await act(async () => {
        await userEvent.click(screen.getByRole("button", { name: /Test connection/i }));
      });

      await waitFor(() => {
        expect(toastSuccess).toHaveBeenCalledWith("Connection successful.");
      });

      const calls = vi.mocked(fetch).mock.calls;
      const postCall = calls.find((c) => (c[1] as RequestInit)?.method === "POST");
      expect(postCall?.[0]).toContain("/ai-provider/test");
    });

    it("shows error toast when test connection fails", async () => {
      globalThis.fetch = vi.fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 404,
          json: async () => ({}),
          text: async () => "",
        } as Response)
        .mockResolvedValueOnce({
          ok: false,
          status: 503,
          json: async () => ({ detail: "Connection refused" }),
          text: async () => "Connection refused",
        } as Response);

      render(<AIProviderCard projectId="p1" />);
      await waitFor(() => screen.getByRole("button", { name: /Test connection/i }));

      await act(async () => {
        await userEvent.click(screen.getByRole("button", { name: /Test connection/i }));
      });

      await waitFor(() => {
        expect(toastError).toHaveBeenCalledWith(expect.stringContaining("Connection failed:"));
      });
    });
  });
});
