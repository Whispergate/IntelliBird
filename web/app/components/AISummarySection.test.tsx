/**
 * AISummarySection tests
 *
 * Covers:
 *   - "Summarise" button when no summary present
 *   - "Re-summarise" button when summary already present
 *   - "Summarising…" + spinner during active stream
 *   - SSE data: chunks accumulate in display div
 *   - 429 → inline budget-exhausted message + toast.error
 *   - Truncation footer rendered separately when present
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

// ---------------------------------------------------------------------------
// EventSource mock — per-test configurable
// ---------------------------------------------------------------------------

type EventSourceListener = (event: MessageEvent | Event) => void;

class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  readyState = MockEventSource.OPEN;
  url: string;
  private listeners: Map<string, EventSourceListener[]> = new Map();
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = MockEventSource.CLOSED;
  });

  constructor(url: string) {
    this.url = url;
    MockEventSource._instances.push(this);
  }

  addEventListener(type: string, listener: EventSourceListener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type)!.push(listener);
  }

  removeEventListener(type: string, listener: EventSourceListener) {
    const arr = this.listeners.get(type) ?? [];
    const idx = arr.indexOf(listener);
    if (idx !== -1) arr.splice(idx, 1);
  }

  // Test helpers to simulate server events
  emit(type: string, data?: string) {
    if (type === "message" && this.onmessage) {
      this.onmessage(new MessageEvent("message", { data }));
    }
    const listeners = this.listeners.get(type) ?? [];
    for (const l of listeners) {
      l(new MessageEvent(type, { data }));
    }
  }

  static _instances: MockEventSource[] = [];
  static reset() {
    MockEventSource._instances = [];
  }
  static lastInstance(): MockEventSource | undefined {
    return MockEventSource._instances[MockEventSource._instances.length - 1];
  }
}

// Install mock before component import
vi.stubGlobal("EventSource", MockEventSource);

// Now import the component
import { AISummarySection } from "./AISummarySection";

const EVENT_ID = "evt-abc123";

describe("AISummarySection", () => {
  beforeEach(() => {
    MockEventSource.reset();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders "Summarise" button when no summary is present', () => {
    render(<AISummarySection eventId={EVENT_ID} />);
    expect(screen.getByRole("button", { name: /summarise/i })).toBeTruthy();
    // "Summarise" — not "Re-summarise"
    const btn = screen.getByRole("button", { name: /summarise/i });
    expect(btn.textContent).toContain("Summarise");
    expect(btn.textContent).not.toContain("Re-summarise");
  });

  it('renders "Re-summarise" button when summary already present', () => {
    render(
      <AISummarySection
        eventId={EVENT_ID}
        aiSummary="Existing summary text"
      />,
    );
    const btn = screen.getByRole("button", { name: /re-summarise/i });
    expect(btn.textContent).toContain("Re-summarise");
  });

  it('shows "Summarising…" and disables button during active stream', async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ job_id: "job-001" }), { status: 200 }),
    );

    render(<AISummarySection eventId={EVENT_ID} />);
    const btn = screen.getByRole("button", { name: /summarise/i });
    await user.click(btn);

    await waitFor(() => {
      // Button should now say "Summarising…" and be disabled
      expect(screen.getByRole("button", { name: /summarising/i })).toBeTruthy();
      const disabledBtn = screen.getByRole("button", { name: /summarising/i });
      expect(disabledBtn).toBeDisabled();
    });
  });

  it("accumulates SSE data: chunks in the summary display div", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ job_id: "job-002" }), { status: 200 }),
    );

    render(<AISummarySection eventId={EVENT_ID} />);
    const btn = screen.getByRole("button", { name: /summarise/i });
    await user.click(btn);

    // Wait for EventSource to be instantiated
    await waitFor(() => {
      expect(MockEventSource.lastInstance()).toBeTruthy();
    });

    const es = MockEventSource.lastInstance()!;

    // Emit SSE tokens
    act(() => {
      es.emit("message", "What: ");
      es.emit("message", "Critical vulnerability ");
      es.emit("message", "in OpenSSL.");
    });

    await waitFor(() => {
      const body = screen.getByTestId("ai-summary-body");
      expect(body.textContent).toContain("What: ");
      expect(body.textContent).toContain("Critical vulnerability ");
      expect(body.textContent).toContain("in OpenSSL.");
    });
  });

  it("stops streaming and shows Re-summarise button on event: done", async () => {
    const user = userEvent.setup();
    // Mock summarise + suggestions fetch
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ job_id: "job-003" }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([]), { status: 200 }),
      );

    render(<AISummarySection eventId={EVENT_ID} />);
    await user.click(screen.getByRole("button", { name: /summarise/i }));

    await waitFor(() => expect(MockEventSource.lastInstance()).toBeTruthy());
    const es = MockEventSource.lastInstance()!;

    act(() => {
      es.emit("message", "Summary content here.");
      es.emit("done");
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /re-summarise/i })).toBeTruthy();
    });
  });

  it("shows inline budget-exhausted message and toast.error on 429", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Budget exhausted" }), {
        status: 429,
      }),
    );

    const { toast } = await import("sonner");
    render(<AISummarySection eventId={EVENT_ID} />);
    await user.click(screen.getByRole("button", { name: /summarise/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/Budget exhausted — resets at 00:00 UTC/i),
      ).toBeTruthy();
    });

    expect(toast.error).toHaveBeenCalledWith(
      "Daily AI budget exhausted — resets at 00:00 UTC.",
    );
  });

  it("renders truncation footer separately when summary contains marker", async () => {
    const summaryWithTruncation =
      "What: A critical CVE.\nWho: Threat actor APT28.\n— Content exceeded model window; summary based on top-ranked chunks";

    render(
      <AISummarySection
        eventId={EVENT_ID}
        aiSummary={summaryWithTruncation}
      />,
    );

    const body = screen.getByTestId("ai-summary-body");
    // Body should NOT contain the truncation line
    expect(body.textContent).not.toContain("— Content exceeded");

    // Footer paragraph should be separate
    const footer = screen.getByText(
      /— Content exceeded model window; summary based on top-ranked chunks/,
    );
    expect(footer.tagName).toBe("P");
  });
});
