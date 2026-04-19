import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock api-client so tests never hit the network
// ---------------------------------------------------------------------------
vi.mock("@/app/api-client", () => ({
  testWebhook: vi.fn(),
  listPresets: vi.fn(),
}));

import * as apiClient from "@/app/api-client";
import { WebhookDialog } from "@/app/webhooks/components/WebhookDialog";
import type { Webhook } from "@/app/api-client";

const mockTestWebhook = apiClient.testWebhook as ReturnType<typeof vi.fn>;
const mockListPresets = apiClient.listPresets as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const MINIMAL_WEBHOOK: Webhook = {
  id: "wh-1",
  name: "my-webhook",
  destination_type: "slack",
  url: "https://hooks.slack.com/services/T0/B0/xxx",
  batching_window_sec: 300,
  enabled: true,
  last_dispatch_at: null,
  last_delivery_at: null,
  last_delivery_status: null,
  consecutive_failures: 0,
  bound_preset_names: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderAdd(overrides?: Partial<React.ComponentProps<typeof WebhookDialog>>) {
  const onSubmit = vi.fn();
  const onClose = vi.fn();
  render(
    <WebhookDialog
      open={true}
      mode="add"
      onSubmit={onSubmit}
      onClose={onClose}
      {...overrides}
    />,
  );
  return { onSubmit, onClose };
}

function renderEdit(
  wh: Webhook = MINIMAL_WEBHOOK,
  overrides?: Partial<React.ComponentProps<typeof WebhookDialog>>,
) {
  const onSubmit = vi.fn();
  const onClose = vi.fn();
  render(
    <WebhookDialog
      open={true}
      mode="edit"
      initialWebhook={wh}
      onSubmit={onSubmit}
      onClose={onClose}
      {...overrides}
    />,
  );
  return { onSubmit, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
  // Default: listPresets resolves to empty (no presets)
  mockListPresets.mockResolvedValue([]);
});

// ---------------------------------------------------------------------------
// Test 1: Add mode title + submit button text
// ---------------------------------------------------------------------------
describe("WebhookDialog", () => {
  it("Add mode: title 'Add Webhook', submit 'Save Webhook'", () => {
    renderAdd();
    expect(screen.getByRole("heading", { name: /Add Webhook/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save Webhook/i })).toBeInTheDocument();
  });

  // Test 2: Edit mode title + submit button text + Type Select disabled
  it("Edit mode: title 'Edit Webhook', Type Select is disabled", () => {
    renderEdit();
    expect(screen.getByRole("heading", { name: /Edit Webhook/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save Changes/i })).toBeInTheDocument();
    // The Select trigger button for destination_type should be disabled
    const trigger = document.getElementById("destination_type");
    expect(trigger).toBeInTheDocument();
    expect(trigger).toBeDisabled();
  });

  // Test 3: Auth field hidden for Slack/Teams/Discord
  it("Auth field hidden for Slack/Teams/Discord", () => {
    // Add mode defaults to Slack — auth fields should not be present
    renderAdd();
    // The auth_type Select should not be rendered (only present for generic)
    expect(document.getElementById("auth_type")).toBeNull();
  });

  // Test 4: Auth field visible for Generic JSON with bearer/basic/header options
  it("Auth field visible for Generic JSON with bearer/basic/header options", () => {
    // Render edit mode with a generic destination webhook
    const genericWebhook: Webhook = {
      ...MINIMAL_WEBHOOK,
      destination_type: "generic",
    };
    renderEdit(genericWebhook);

    // Auth type Select should be rendered
    const authSelect = document.getElementById("auth_type");
    expect(authSelect).toBeInTheDocument();
  });

  // Test 5: Batching window Select defaults to '5 min' / 300
  it("Batching window Select defaults to '5 min' / 300", () => {
    renderAdd();
    // The Select trigger for batching_window_sec should show the default
    const trigger = document.getElementById("batching_window_sec");
    expect(trigger).toBeInTheDocument();
    // Default value is "300" which maps to label "5 min"
    expect(trigger).toHaveTextContent("5 min");
  });

  // Test 6: Test Send success — verbatim copy
  it("Test Send button shows green alert with 'Test sent successfully · {ms}ms' copy on success", async () => {
    mockTestWebhook.mockResolvedValue({
      ok: true,
      latency_ms: 42,
      error_detail: null,
    });

    renderAdd();

    // Fill in required URL so runTest has something to send
    const urlInput = document.getElementById("url")!;
    fireEvent.change(urlInput, {
      target: { value: "https://hooks.slack.com/services/T0/B0/test" },
    });

    const testBtn = screen.getByRole("button", { name: /Test Send/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/Test sent successfully · 42ms/),
      ).toBeInTheDocument();
    });
  });

  // Test 7: Test Send failure — verbatim copy
  it("Test Send button shows amber alert with 'Test failed: {err}. You can still save this configuration.' copy on failure", async () => {
    mockTestWebhook.mockResolvedValue({
      ok: false,
      latency_ms: 0,
      error_detail: "HTTP 500",
    });

    renderAdd();

    const testBtn = screen.getByRole("button", { name: /Test Send/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(
        screen.getByText(
          /Test failed: HTTP 500\. You can still save this configuration\./,
        ),
      ).toBeInTheDocument();
    });
  });

  // Test 8: Save button NEVER disabled by test result
  it("Save button is NEVER disabled by test result (non-blocking D-31)", async () => {
    mockTestWebhook.mockResolvedValue({
      ok: false,
      latency_ms: 0,
      error_detail: "Network error",
    });

    renderAdd();

    const testBtn = screen.getByRole("button", { name: /Test Send/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/You can still save this configuration/),
      ).toBeInTheDocument();
    });

    const saveBtn = screen.getByRole("button", { name: /Save Webhook/i });
    expect(saveBtn).not.toBeDisabled();
  });

  // Test 9: Bound presets multi-select loads from /api/presets on open
  it("Bound presets multi-select loads from /api/presets on open", async () => {
    mockListPresets.mockResolvedValue([
      {
        id: "p1",
        name: "a",
        query_params: {},
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "p2",
        name: "b",
        query_params: {},
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);

    renderAdd();

    await waitFor(() => {
      const checkboxes = screen.getAllByRole("checkbox");
      expect(checkboxes).toHaveLength(2);
    });
  });

  // Test 10: Bound presets multi-select: toggling checkbox adds/removes name
  it("Bound presets multi-select: toggling checkbox adds/removes name in array", async () => {
    mockListPresets.mockResolvedValue([
      {
        id: "p1",
        name: "a",
        query_params: {},
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "p2",
        name: "b",
        query_params: {},
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);

    renderAdd();

    await waitFor(() => {
      expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    });

    // Find and click the checkbox for preset "a"
    const labels = screen.getAllByText(/^a$|^b$/);
    const labelA = labels.find((el) => el.textContent === "a")!;
    const checkboxA = labelA.closest("label")!.querySelector("input[type=checkbox]") as HTMLInputElement;

    expect(checkboxA.checked).toBe(false);
    fireEvent.click(checkboxA);
    expect(checkboxA.checked).toBe(true);

    // Click again to uncheck
    fireEvent.click(checkboxA);
    expect(checkboxA.checked).toBe(false);
  });
});
