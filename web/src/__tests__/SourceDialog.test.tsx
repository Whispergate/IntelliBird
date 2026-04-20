import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock api-client so tests never hit the network
// ---------------------------------------------------------------------------
vi.mock("@/app/api-client", () => ({
  testConnection: vi.fn(),
  // SourceDialog fetches the template list on mount in add mode.
  // Return an empty list so the effect resolves cleanly.
  fetchSourceTemplates: vi.fn().mockResolvedValue([]),
}));

import * as apiClient from "@/app/api-client";
import { SourceDialog } from "@/app/sources/components/SourceDialog";
import type { Source } from "@/app/api-client";

const mockTestConnection = apiClient.testConnection as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const MINIMAL_SOURCE: Source = {
  id: "src-1",
  name: "My Feed",
  feed_type: "nvd",
  url: "https://nvd.nist.gov/",
  poll_interval_sec: 3600,
  hot_retention_days: 30,
  archive_policy: "drop",
  enabled: true,
  last_polled_at: null,
  last_status: null,
  consecutive_failures: 0,
  silent_failure_count: 0,
  effective_status: null,
  created_at: "2026-01-01T00:00:00Z",
};

function renderAdd(overrides?: Partial<React.ComponentProps<typeof SourceDialog>>) {
  const onSubmit = vi.fn();
  const onClose = vi.fn();
  render(
    <SourceDialog
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
  src: Source = MINIMAL_SOURCE,
  overrides?: Partial<React.ComponentProps<typeof SourceDialog>>,
) {
  const onSubmit = vi.fn();
  const onClose = vi.fn();
  render(
    <SourceDialog
      open={true}
      mode="edit"
      initialSource={src}
      onSubmit={onSubmit}
      onClose={onClose}
      {...overrides}
    />,
  );
  return { onSubmit, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Add mode heading + submit label
// ---------------------------------------------------------------------------
describe("SourceDialog — Add mode", () => {
  it("renders 'Add Source' heading and 'Save Source' submit label", () => {
    renderAdd();
    expect(
      screen.getByRole("heading", { name: /Add Source/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Save Source/i }),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 2. Edit mode heading + submit label
// ---------------------------------------------------------------------------
describe("SourceDialog — Edit mode", () => {
  it("renders 'Edit Source' heading and 'Save Changes' submit label", () => {
    renderEdit();
    expect(
      screen.getByRole("heading", { name: /Edit Source/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Save Changes/i }),
    ).toBeInTheDocument();
  });

  // 3. Feed type locked on edit
  it("disables Type Select and shows 'Feed type cannot be changed after creation.' helper", () => {
    renderEdit();
    // The trigger button for the Select should be disabled
    const trigger = document.getElementById("feed_type");
    expect(trigger).toBeInTheDocument();
    expect(trigger).toBeDisabled();
    expect(
      screen.getByText("Feed type cannot be changed after creation."),
    ).toBeInTheDocument();
  });

  // 4. Edit mode credential inputs show the verbatim placeholder
  it("shows '(unchanged — type to replace)' placeholder on credential inputs", () => {
    // NVD source: one password input visible
    renderEdit(MINIMAL_SOURCE);
    const passwordInputs = document.querySelectorAll<HTMLInputElement>(
      'input[type="password"]',
    );
    expect(passwordInputs.length).toBeGreaterThanOrEqual(1);
    for (const input of passwordInputs) {
      expect(input.placeholder).toBe("(unchanged — type to replace)");
    }
  });
});

// ---------------------------------------------------------------------------
// 5. Type=RSS hides credentials section entirely
// ---------------------------------------------------------------------------
describe("SourceDialog — credentials visibility", () => {
  it("Type=RSS hides credentials section (no password inputs)", () => {
    // Default add mode uses RSS
    renderAdd();
    const passwordInputs = document.querySelectorAll('input[type="password"]');
    expect(passwordInputs).toHaveLength(0);
  });

  // 6. Type=NVD shows single API key input
  it("Type=NVD shows single password API key input with autoComplete=off", async () => {
    // Render with NVD as default so we don't need to interact with the Select portal
    render(
      <SourceDialog
        open={true}
        mode="add"
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    // Change feed_type to nvd by rendering an edit source with nvd type
    // Since select portal is hard to test, we rely on the Edit mode test with initialSource
    // and directly test the NVD credentials field is visible when feed_type=nvd

    // Instead render with initialSource so feed_type=nvd is pre-selected
    render(
      <SourceDialog
        open={true}
        mode="edit"
        initialSource={MINIMAL_SOURCE}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    // NVD source — should see the API key password input
    const passwordInputs = document.querySelectorAll<HTMLInputElement>(
      'input[type="password"]',
    );
    expect(passwordInputs.length).toBeGreaterThanOrEqual(1);
    expect(passwordInputs[0].autocomplete).toBe("off");
  });
});

// ---------------------------------------------------------------------------
// 7. Test Connection success → green alert
// ---------------------------------------------------------------------------
describe("SourceDialog — Test Connection", () => {
  it("success renders 'Connection OK · Xms · N items sampled' in alert", async () => {
    mockTestConnection.mockResolvedValue({
      ok: true,
      latency_ms: 42,
      item_count_sampled: 5,
      error_detail: null,
    });

    renderAdd();

    // Fill in a valid URL so the test can proceed
    const urlInput = document.getElementById("url")!;
    fireEvent.change(urlInput, { target: { value: "https://example.com/" } });

    const testBtn = screen.getByRole("button", { name: /Test Connection/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/Connection OK.*42ms.*5 items sampled/i),
      ).toBeInTheDocument();
    });
  });

  // 8. Test Connection failure → amber alert with exact copy
  it("failure renders 'Test failed: X. You can still save this configuration.' in alert", async () => {
    mockTestConnection.mockResolvedValue({
      ok: false,
      latency_ms: 0,
      item_count_sampled: 0,
      error_detail: "Connection refused",
    });

    renderAdd();

    const testBtn = screen.getByRole("button", { name: /Test Connection/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(
        screen.getByText(
          /Test failed: Connection refused\. You can still save this configuration\./i,
        ),
      ).toBeInTheDocument();
    });
  });

  // 9. Save button remains enabled after a failed Test Connection
  it("Save button remains enabled after a failed Test Connection", async () => {
    mockTestConnection.mockResolvedValue({
      ok: false,
      latency_ms: 0,
      item_count_sampled: 0,
      error_detail: "Timeout",
    });

    renderAdd();

    const testBtn = screen.getByRole("button", { name: /Test Connection/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/You can still save this configuration/i),
      ).toBeInTheDocument();
    });

    const saveBtn = screen.getByRole("button", { name: /Save Source/i });
    expect(saveBtn).not.toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// 10–11. Inline validation errors
// ---------------------------------------------------------------------------
describe("SourceDialog — validation", () => {
  it("invalid URL shows inline error 'A valid URL is required'", async () => {
    renderAdd();

    // Submit without filling the URL
    const saveBtn = screen.getByRole("button", { name: /Save Source/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(
        screen.getByText("A valid URL is required"),
      ).toBeInTheDocument();
    });
  });

  it("missing Name shows inline error 'Name is required'", async () => {
    renderAdd();

    const saveBtn = screen.getByRole("button", { name: /Save Source/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText("Name is required")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// 12. Custom retention preset reveals hot_retention_days + archive_policy
// ---------------------------------------------------------------------------
describe("SourceDialog — RetentionPresetPicker", () => {
  it("Custom retention preset reveals hot_retention_days and archive_policy inputs", async () => {
    renderAdd();

    // Custom radio button
    const customRadio = document.getElementById("preset-custom")!;
    expect(customRadio).toBeInTheDocument();
    fireEvent.click(customRadio);

    await waitFor(() => {
      expect(
        document.getElementById("hot_retention_days_custom"),
      ).toBeInTheDocument();
      expect(
        document.getElementById("archive_policy_custom"),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// 13. Valid Add form calls onSubmit with buildCreatePayload shape
// ---------------------------------------------------------------------------
describe("SourceDialog — submit", () => {
  it("valid Add form calls onSubmit with expected payload shape", async () => {
    const { onSubmit } = renderAdd();

    // Fill Name
    fireEvent.change(document.getElementById("name")!, {
      target: { value: "My RSS Feed" },
    });
    // Fill URL
    fireEvent.change(document.getElementById("url")!, {
      target: { value: "https://feeds.example.com/rss" },
    });

    const saveBtn = screen.getByRole("button", { name: /Save Source/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });

    const payload = onSubmit.mock.calls[0][0];
    expect(payload).toMatchObject({
      name: "My RSS Feed",
      feed_type: "rss",
      url: "https://feeds.example.com/rss",
      poll_interval_sec: expect.any(Number),
      hot_retention_days: expect.any(Number),
      archive_policy: expect.any(String),
      enabled: true,
    });
  });

  // 14. Edit form without touching credentials OMITS credentials key
  it("Edit form without touching credentials omits credentials key", async () => {
    const { onSubmit } = renderEdit(MINIMAL_SOURCE);

    // Name and URL are pre-filled; just submit
    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });

    const payload = onSubmit.mock.calls[0][0];
    expect(payload).not.toHaveProperty("credentials");
  });

  // 15. Edit form with credentials typed INCLUDES credentials key
  it("Edit form with credentials typed includes credentials key in payload", async () => {
    const { onSubmit } = renderEdit(MINIMAL_SOURCE);

    // Type into the NVD API Key field
    const apiKeyInput = document.getElementById("nvd_api_key")!;
    fireEvent.change(apiKeyInput, { target: { value: "my-api-key-123" } });

    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledOnce();
    });

    const payload = onSubmit.mock.calls[0][0];
    expect(payload).toHaveProperty("credentials");
    expect(payload.credentials).toMatchObject({
      type: "apiKey",
      key: "my-api-key-123",
    });
  });
});
