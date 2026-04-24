import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { WebhookTable } from "../../app/webhooks/components/WebhookTable";
import { WebhooksClient } from "../../app/webhooks/WebhooksClient";
import type { Webhook } from "../../app/api-client";

// Mock the api-client — all webhook fetchers used by WebhooksClient + WebhookTable
vi.mock("../../app/api-client", () => ({
  updateWebhook: vi.fn(),
  createWebhook: vi.fn(),
  deleteWebhook: vi.fn(),
  listWebhooks: vi.fn(),
  testWebhook: vi.fn(),
  listPresets: vi.fn(),
}));

// Mock sonner
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

// Stub window.confirm globally
vi.stubGlobal("confirm", vi.fn());

import {
  updateWebhook,
  createWebhook,
  deleteWebhook,
  listWebhooks,
  listPresets,
} from "../../app/api-client";
import { toast } from "sonner";

function makeWebhook(overrides: Partial<Webhook> = {}): Webhook {
  return {
    id: "wh-1",
    name: "Alpha Webhook",
    project_id: "00000000-0000-0000-0000-000000000001",
    destination_type: "slack",
    url: "https://hooks.slack.com/services/T000/B000/xxxx",
    batching_window_sec: 300,
    enabled: true,
    last_dispatch_at: null,
    last_delivery_at: "2026-04-17T10:00:00Z",
    last_delivery_status: "ok",
    consecutive_failures: 0,
    bound_preset_names: [],
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-17T10:00:00Z",
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
  // Default: listPresets returns empty (avoids unhandled promise rejection in dialog)
  vi.mocked(listPresets).mockResolvedValue([]);
});

describe("WebhooksClient", () => {
  it("renders empty state when no webhooks", () => {
    render(<WebhooksClient initialWebhooks={[]} />);
    expect(screen.getByRole("heading", { name: "Webhooks" })).toBeDefined();
    expect(screen.getByText("Register outbound alert destinations.")).toBeDefined();
    expect(screen.getByText("No webhooks yet.")).toBeDefined();
    expect(
      screen.getByText("Add your first destination to start receiving alerts.")
    ).toBeDefined();
  });

  it("opens Add dialog when Add button clicked", async () => {
    render(<WebhooksClient initialWebhooks={[]} />);
    // Header-level Add Webhook button
    const buttons = screen.getAllByRole("button", { name: /Add Webhook/i });
    fireEvent.click(buttons[0]);
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });
    expect(screen.getByRole("heading", { name: "Add Webhook" })).toBeDefined();
  });

  it("refreshes list after create", async () => {
    const newWh = makeWebhook({ id: "wh-2", name: "new-webhook" });
    vi.mocked(createWebhook).mockResolvedValueOnce(newWh);
    vi.mocked(listWebhooks).mockResolvedValueOnce([newWh]);

    render(<WebhooksClient initialWebhooks={[]} />);

    // Open add dialog
    const addBtn = screen.getAllByRole("button", { name: /Add Webhook/i })[0];
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });

    // Fill in required fields (name must match schema: lowercase/digits/hyphen/underscore)
    const nameInput = screen.getByLabelText(/Name/i);
    fireEvent.change(nameInput, { target: { value: "new-webhook" } });
    const urlInput = screen.getByLabelText(/URL/i);
    fireEvent.change(urlInput, { target: { value: "https://hooks.slack.com/services/T000/B000/xxxx" } });

    // Submit
    const saveBtn = screen.getByRole("button", { name: /Save Webhook/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Webhook added.");
    });
    await waitFor(() => {
      expect(listWebhooks).toHaveBeenCalled();
    });
  });

  it("refreshes list after update", async () => {
    const wh = makeWebhook({ name: "test-webhook" });
    const updated = makeWebhook({ name: "test-webhook-updated" });
    vi.mocked(updateWebhook).mockResolvedValueOnce(updated);
    vi.mocked(listWebhooks).mockResolvedValueOnce([updated]);

    render(<WebhooksClient initialWebhooks={[wh]} />);

    // Click row to open edit dialog
    const nameCell = screen.getByText("test-webhook");
    fireEvent.click(nameCell);

    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeDefined();
    });

    expect(screen.getByRole("heading", { name: "Edit Webhook" })).toBeDefined();

    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Webhook updated.");
    });
    await waitFor(() => {
      expect(listWebhooks).toHaveBeenCalled();
    });
  });

  it("optimistically removes row on delete", async () => {
    const wh = makeWebhook({ name: "test-webhook" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(deleteWebhook).mockResolvedValueOnce(undefined);

    const { baseElement } = render(<WebhooksClient initialWebhooks={[wh]} />);

    // Open the actions dropdown
    const actionsBtn = screen.getByRole("button", { name: /Actions for test-webhook/i });
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
      expect(deleteWebhook).toHaveBeenCalledWith("wh-1");
    });
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Webhook deleted.");
    });

    // Row should be removed
    await waitFor(() => {
      expect(screen.queryByText("test-webhook")).toBeNull();
    });
  });

  it("shows native confirm with preset-binding-count copy", async () => {
    const wh = makeWebhook({
      name: "test-webhook",
      bound_preset_names: ["preset-a", "preset-b"],
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    const { baseElement } = render(<WebhooksClient initialWebhooks={[wh]} />);

    const actionsBtn = screen.getByRole("button", { name: /Actions for test-webhook/i });
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
    expect(msg).toBe(
      'Delete webhook "test-webhook"? 2 bindings will be removed. No historical deliveries are tracked.'
    );
  });
});

describe("WebhookTable", () => {
  it("renders 7 columns: Name, Type, URL, Bound Presets, Status, Enabled, Actions", () => {
    render(
      <WebhookTable
        initialWebhooks={[makeWebhook()]}
        {...DEFAULT_PROPS}
      />,
    );
    const headers = screen.getAllByRole("columnheader");
    const headerTexts = headers.map((h) => h.textContent?.trim() ?? "");
    expect(headerTexts).toHaveLength(7);
    expect(headerTexts[0]).toContain("Name");
    expect(headerTexts[1]).toContain("Type");
    expect(headerTexts[2]).toContain("URL");
    expect(headerTexts[3]).toContain("Bound Presets");
    expect(headerTexts[4]).toContain("Status");
    expect(headerTexts[5]).toContain("Enabled");
    expect(headerTexts[6]).toContain("Actions");
  });

  it("optimistic Switch toggle reverts on API error", async () => {
    const mockUpdateWebhook = vi.mocked(updateWebhook);
    mockUpdateWebhook.mockRejectedValueOnce(new Error("API failure"));

    const webhook = makeWebhook({ enabled: true });
    render(
      <WebhookTable
        initialWebhooks={[webhook]}
        {...DEFAULT_PROPS}
      />,
    );

    const switchEl = screen.getByRole("switch");
    // Initial state should be checked
    expect(switchEl.getAttribute("data-state")).toBe("checked");

    fireEvent.click(switchEl);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Could not update webhook. Reverted.");
    });

    // Switch should revert back to checked (enabled=true)
    await waitFor(() => {
      expect(switchEl.getAttribute("data-state")).toBe("checked");
    });
  });

  it("status badge shows never-delivered when last_delivery_at null", () => {
    const webhook = makeWebhook({
      last_delivery_at: null,
      last_delivery_status: null,
    });
    render(
      <WebhookTable
        initialWebhooks={[webhook]}
        {...DEFAULT_PROPS}
      />,
    );
    // Badge text should contain "Never delivered"
    expect(screen.getByText("Never delivered")).toBeDefined();
  });

  it("bound presets render as chips", () => {
    const webhook = makeWebhook({
      bound_preset_names: ["alpha", "beta"],
    });
    render(
      <WebhookTable
        initialWebhooks={[webhook]}
        {...DEFAULT_PROPS}
      />,
    );
    expect(screen.getByText("alpha")).toBeDefined();
    expect(screen.getByText("beta")).toBeDefined();
  });
});
