import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SourceTable } from "../../app/sources/components/SourceTable";
import type { Source } from "../../app/api-client";

// Mock the api-client
vi.mock("../../app/api-client", () => ({
  updateSource: vi.fn(),
}));

// Mock sonner
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

import { updateSource } from "../../app/api-client";
import { toast } from "sonner";

function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    id: "src-1",
    name: "Alpha Feed",
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

const DEFAULT_PROPS = {
  onAdd: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SourceTable", () => {
  it("renders 8 column headers in the correct order", () => {
    render(
      <SourceTable
        initialSources={[makeSource()]}
        {...DEFAULT_PROPS}
      />
    );
    const headers = screen.getAllByRole("columnheader");
    const headerTexts = headers.map((h) => h.textContent?.trim().replace(/[↑↓]/, "").trim());
    // Check all 8 column names appear in order
    expect(headerTexts[0]).toContain("Name");
    expect(headerTexts[1]).toContain("Type");
    expect(headerTexts[2]).toContain("URL");
    expect(headerTexts[3]).toContain("Interval");
    expect(headerTexts[4]).toContain("Last Polled");
    expect(headerTexts[5]).toContain("Status");
    expect(headerTexts[6]).toContain("Enabled");
    expect(headerTexts[7]).toContain("Actions");
  });

  it("renders empty state when sources is empty", () => {
    render(
      <SourceTable initialSources={[]} {...DEFAULT_PROPS} />
    );
    expect(screen.getByText("No sources yet.")).toBeDefined();
    expect(
      screen.getByText("Add your first feed to start ingesting threat intelligence.")
    ).toBeDefined();

    const addBtn = screen.getByRole("button", { name: /Add Source/i });
    fireEvent.click(addBtn);
    expect(DEFAULT_PROPS.onAdd).toHaveBeenCalledTimes(1);
  });

  it("sorts by name ascending when Name header clicked twice", () => {
    const sources = [
      makeSource({ id: "1", name: "Zeta Feed", last_polled_at: "2026-04-17T08:00:00Z" }),
      makeSource({ id: "2", name: "Alpha Feed", last_polled_at: "2026-04-17T09:00:00Z" }),
    ];
    render(<SourceTable initialSources={sources} {...DEFAULT_PROPS} />);

    const nameHeader = screen.getByRole("columnheader", { name: /Name/i });
    // First click: sort by name desc
    fireEvent.click(nameHeader);
    // Second click: sort by name asc
    fireEvent.click(nameHeader);

    const rows = screen.getAllByRole("row");
    // rows[0] is header, rows[1] is first data row
    expect(rows[1].textContent).toContain("Alpha Feed");
    expect(rows[2].textContent).toContain("Zeta Feed");
  });

  it("default sort is last_polled_at DESC NULLS LAST", () => {
    const sources = [
      makeSource({ id: "1", name: "Early", last_polled_at: "2026-04-17T09:00:00Z" }),
      makeSource({ id: "2", name: "Latest", last_polled_at: "2026-04-17T10:00:00Z" }),
      makeSource({ id: "3", name: "Never", last_polled_at: null }),
    ];
    render(<SourceTable initialSources={sources} {...DEFAULT_PROPS} />);

    const rows = screen.getAllByRole("row");
    // Default: desc, so Latest first, Early second, Never (null) last
    expect(rows[1].textContent).toContain("Latest");
    expect(rows[2].textContent).toContain("Early");
    expect(rows[3].textContent).toContain("Never");
  });

  it("disabled rows have opacity-60 class", () => {
    const source = makeSource({ enabled: false });
    render(<SourceTable initialSources={[source]} {...DEFAULT_PROPS} />);

    const rows = screen.getAllByRole("row");
    // rows[1] is the data row
    expect(rows[1].className).toContain("opacity-60");
  });

  it("Switch toggle calls updateSource optimistically", async () => {
    const mockUpdateSource = vi.mocked(updateSource);
    const resolved = makeSource({ enabled: false });
    mockUpdateSource.mockResolvedValueOnce(resolved);

    const source = makeSource({ enabled: true });
    render(<SourceTable initialSources={[source]} {...DEFAULT_PROPS} />);

    const switchEl = screen.getByRole("switch");
    fireEvent.click(switchEl);

    // updateSource should be called with the new toggled value
    await waitFor(() => {
      expect(mockUpdateSource).toHaveBeenCalledWith(source.id, { enabled: false });
    });
  });

  it("Switch toggle reverts and toasts on API error", async () => {
    const mockUpdateSource = vi.mocked(updateSource);
    mockUpdateSource.mockRejectedValueOnce(new Error("API failure"));

    const source = makeSource({ enabled: true });
    render(<SourceTable initialSources={[source]} {...DEFAULT_PROPS} />);

    const switchEl = screen.getByRole("switch");
    // Check initial state is checked
    expect(switchEl.getAttribute("data-state")).toBe("checked");

    fireEvent.click(switchEl);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Could not update source. Reverted.");
    });

    // Switch should revert back to checked (enabled=true)
    await waitFor(() => {
      expect(switchEl.getAttribute("data-state")).toBe("checked");
    });
  });

  it("row click invokes onEdit with source", () => {
    const source = makeSource();
    render(<SourceTable initialSources={[source]} {...DEFAULT_PROPS} />);

    // Click on the name cell (not Switch or Actions)
    const nameCell = screen.getByText("Alpha Feed");
    fireEvent.click(nameCell);

    expect(DEFAULT_PROPS.onEdit).toHaveBeenCalledWith(source);
  });

  it("Actions menu Delete item invokes onDelete and has destructive class", async () => {
    const source = makeSource();
    const { baseElement } = render(
      <SourceTable initialSources={[source]} {...DEFAULT_PROPS} />
    );

    // Click the actions trigger button
    const actionsBtn = screen.getByRole("button", { name: /Actions for Alpha Feed/i });
    fireEvent.click(actionsBtn);
    fireEvent.pointerDown(actionsBtn);

    // Radix portals append to document.body; use baseElement to search
    await waitFor(() => {
      // Try to find Delete in the whole document
      const allItems = baseElement.querySelectorAll('[role="menuitem"]');
      const deleteItem = Array.from(allItems).find((el) =>
        el.textContent?.includes("Delete")
      );
      expect(deleteItem).toBeDefined();
      expect(deleteItem?.className).toContain("text-destructive");
      fireEvent.click(deleteItem!);
    });

    expect(DEFAULT_PROPS.onDelete).toHaveBeenCalledWith(source);
  });

  it("URL cell uses brand-mono and truncates", () => {
    const source = makeSource({ url: "https://example.com/feed.xml" });
    render(<SourceTable initialSources={[source]} {...DEFAULT_PROPS} />);

    const urlCell = screen.getByText("https://example.com/feed.xml");
    expect(urlCell.className).toContain("brand-mono");
    expect(urlCell.className).toContain("truncate");
    expect(urlCell.className).toContain("max-w-[240px]");
  });
});
