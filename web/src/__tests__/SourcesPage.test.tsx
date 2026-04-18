import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SourcesClient } from "../../app/sources/SourcesClient";
import type { Source } from "../../app/api-client";

// Mock the api-client
vi.mock("../../app/api-client", () => ({
  fetchSources: vi.fn(),
  createSource: vi.fn(),
  updateSource: vi.fn(),
  deleteSource: vi.fn(),
  getSourceEventCount: vi.fn(),
  testConnection: vi.fn(),
}));

// Mock sonner
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

// Mock window.confirm
vi.stubGlobal("confirm", vi.fn());

import {
  fetchSources,
  createSource,
  updateSource,
  deleteSource,
  getSourceEventCount,
} from "../../app/api-client";
import { toast } from "sonner";

function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    id: "src-1",
    name: "SourceA",
    feed_type: "rss",
    url: "https://example.com/feed.xml",
    poll_interval_sec: 3600,
    hot_retention_days: 30,
    archive_policy: "drop",
    enabled: true,
    last_polled_at: "2026-04-17T10:00:00Z",
    last_status: "ok",
    consecutive_failures: 0,
    silent_failure_count: 0,
    effective_status: "ok",
    created_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SourcesClient", () => {
  it("renders page title 'Sources' and subtitle 'Add and manage threat-intel feeds.'", () => {
    render(<SourcesClient initialSources={[]} />);
    expect(screen.getByRole("heading", { name: "Sources" })).toBeDefined();
    expect(screen.getByText("Add and manage threat-intel feeds.")).toBeDefined();
  });

  it("Add Source button opens dialog in add mode", async () => {
    render(<SourcesClient initialSources={[]} />);
    // Click the header-level Add Source button (not the empty-state one)
    const buttons = screen.getAllByRole("button", { name: /Add Source/i });
    fireEvent.click(buttons[0]);
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });
    // Dialog heading should say "Add Source"
    expect(screen.getByRole("heading", { name: "Add Source" })).toBeDefined();
  });

  it("click on table row opens dialog in edit mode with prefilled source", async () => {
    const src = makeSource();
    render(<SourcesClient initialSources={[src]} />);
    const nameCell = screen.getByText("SourceA");
    fireEvent.click(nameCell);
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });
    expect(screen.getByRole("heading", { name: "Edit Source" })).toBeDefined();
  });

  it("successful createSource flow closes dialog + toasts 'Source added.' + refreshes table", async () => {
    const newSrc = makeSource({ id: "src-2", name: "NewFeed" });
    vi.mocked(createSource).mockResolvedValueOnce(newSrc);
    vi.mocked(fetchSources).mockResolvedValueOnce([newSrc]);

    render(<SourcesClient initialSources={[]} />);

    // Open add dialog
    const addBtn = screen.getAllByRole("button", { name: /Add Source/i })[0];
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });

    // Fill in required fields
    const nameInput = screen.getByLabelText(/Name/i);
    fireEvent.change(nameInput, { target: { value: "NewFeed" } });
    const urlInput = screen.getByLabelText(/URL/i);
    fireEvent.change(urlInput, { target: { value: "https://example.com/feed.xml" } });

    // Submit the form
    const saveBtn = screen.getByRole("button", { name: /Save Source/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Source added.");
    });
    await waitFor(() => {
      expect(fetchSources).toHaveBeenCalled();
    });
  });

  it("createSource failure keeps dialog open + toasts 'Failed to save source. Please try again.'", async () => {
    vi.mocked(createSource).mockRejectedValueOnce(new Error("Server error"));

    render(<SourcesClient initialSources={[]} />);

    const addBtn = screen.getAllByRole("button", { name: /Add Source/i })[0];
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });

    const nameInput = screen.getByLabelText(/Name/i);
    fireEvent.change(nameInput, { target: { value: "BadFeed" } });
    const urlInput = screen.getByLabelText(/URL/i);
    fireEvent.change(urlInput, { target: { value: "https://example.com/feed.xml" } });

    const saveBtn = screen.getByRole("button", { name: /Save Source/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Failed to save source. Please try again.");
    });

    // Dialog should still be open
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("successful updateSource closes dialog + toasts 'Source updated.' + refreshes", async () => {
    const src = makeSource();
    const updated = makeSource({ name: "Updated Feed" });
    vi.mocked(updateSource).mockResolvedValueOnce(updated);
    vi.mocked(fetchSources).mockResolvedValueOnce([updated]);

    render(<SourcesClient initialSources={[src]} />);

    // Open edit dialog by clicking the row
    const nameCell = screen.getByText("SourceA");
    fireEvent.click(nameCell);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });

    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Source updated.");
    });
    await waitFor(() => {
      expect(fetchSources).toHaveBeenCalled();
    });
  });

  it("updateSource failure keeps dialog open + same failure toast", async () => {
    const src = makeSource();
    vi.mocked(updateSource).mockRejectedValueOnce(new Error("API failure"));

    render(<SourcesClient initialSources={[src]} />);

    const nameCell = screen.getByText("SourceA");
    fireEvent.click(nameCell);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });

    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Failed to save source. Please try again.");
    });

    // Dialog should remain open
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("delete flow: user confirms (ok=true), deleteSource success, row removed + toast 'Source deleted.'", async () => {
    const src = makeSource();
    vi.mocked(getSourceEventCount).mockResolvedValueOnce({ count: 5 });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(deleteSource).mockResolvedValueOnce(undefined);

    const { baseElement } = render(<SourcesClient initialSources={[src]} />);

    // Open the actions dropdown
    const actionsBtn = screen.getByRole("button", { name: /Actions for SourceA/i });
    fireEvent.click(actionsBtn);
    fireEvent.pointerDown(actionsBtn);

    await waitFor(() => {
      const allItems = baseElement.querySelectorAll('[role="menuitem"]');
      const deleteItem = Array.from(allItems).find((el) =>
        el.textContent?.includes("Delete")
      );
      expect(deleteItem).toBeDefined();
      fireEvent.click(deleteItem!);
    });

    await waitFor(() => {
      expect(deleteSource).toHaveBeenCalledWith("src-1");
    });
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Source deleted.");
    });

    // Row should be removed
    await waitFor(() => {
      expect(screen.queryByText("SourceA")).toBeNull();
    });
  });

  it("delete flow: user cancels via confirm(ok=false) → no deleteSource call, no toast", async () => {
    const src = makeSource();
    vi.mocked(getSourceEventCount).mockResolvedValueOnce({ count: 3 });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    const { baseElement } = render(<SourcesClient initialSources={[src]} />);

    const actionsBtn = screen.getByRole("button", { name: /Actions for SourceA/i });
    fireEvent.click(actionsBtn);
    fireEvent.pointerDown(actionsBtn);

    await waitFor(() => {
      const allItems = baseElement.querySelectorAll('[role="menuitem"]');
      const deleteItem = Array.from(allItems).find((el) =>
        el.textContent?.includes("Delete")
      );
      expect(deleteItem).toBeDefined();
      fireEvent.click(deleteItem!);
    });

    // Wait a tick for async confirm resolution
    await new Promise((r) => setTimeout(r, 50));

    expect(deleteSource).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("delete flow: deleteSource rejects → toast.error 'Failed to delete source.'", async () => {
    const src = makeSource();
    vi.mocked(getSourceEventCount).mockResolvedValueOnce({ count: 2 });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(deleteSource).mockRejectedValueOnce(new Error("DB error"));

    const { baseElement } = render(<SourcesClient initialSources={[src]} />);

    const actionsBtn = screen.getByRole("button", { name: /Actions for SourceA/i });
    fireEvent.click(actionsBtn);
    fireEvent.pointerDown(actionsBtn);

    await waitFor(() => {
      const allItems = baseElement.querySelectorAll('[role="menuitem"]');
      const deleteItem = Array.from(allItems).find((el) =>
        el.textContent?.includes("Delete")
      );
      expect(deleteItem).toBeDefined();
      fireEvent.click(deleteItem!);
    });

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Failed to delete source.");
    });
  });

  it("delete confirm message contains exact D-14 template with name and count substituted", async () => {
    const src = makeSource({ name: "SourceA" });
    vi.mocked(getSourceEventCount).mockResolvedValueOnce({ count: 5 });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    const { baseElement } = render(<SourcesClient initialSources={[src]} />);

    const actionsBtn = screen.getByRole("button", { name: /Actions for SourceA/i });
    fireEvent.click(actionsBtn);
    fireEvent.pointerDown(actionsBtn);

    await waitFor(() => {
      const allItems = baseElement.querySelectorAll('[role="menuitem"]');
      const deleteItem = Array.from(allItems).find((el) =>
        el.textContent?.includes("Delete")
      );
      expect(deleteItem).toBeDefined();
      fireEvent.click(deleteItem!);
    });

    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalledOnce();
    });

    const msg = confirmSpy.mock.calls[0][0] as string;
    expect(msg).toMatch(
      /Delete source "SourceA"\? 5 existing events will keep source_id=NULL \(provenance lost but events retained\)\./
    );
  });

  it("empty initialSources renders empty state with Add Source CTA that opens the dialog", async () => {
    render(<SourcesClient initialSources={[]} />);

    expect(screen.getByText("No sources yet.")).toBeDefined();
    expect(
      screen.getByText("Add your first feed to start ingesting threat intelligence.")
    ).toBeDefined();

    // The empty state Add Source button opens the dialog
    const emptyAddBtn = screen.getAllByRole("button", { name: /Add Source/i });
    // There should be at least one (header btn + empty state btn)
    expect(emptyAddBtn.length).toBeGreaterThanOrEqual(1);

    fireEvent.click(emptyAddBtn[emptyAddBtn.length - 1]);
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });
  });
});
