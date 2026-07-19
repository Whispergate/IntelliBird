/**
 * Tests for OPSEC warning banner and checkbox in SourceDialog for dark-web source types.
 * DARK-07.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock api-client so tests never hit the network
// ---------------------------------------------------------------------------
vi.mock("@/app/api-client", () => ({
  testConnection: vi.fn(),
  fetchSourceTemplates: vi.fn().mockResolvedValue([]),
}));

import { SourceDialog } from "@/app/sources/components/SourceDialog";
import { OPSEC_WARNING_TEXT } from "@/app/sources/lib/sourceSchema";
import type { Source } from "@/app/api-client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal Source shape re-used across tests; feed_type is overridden per test. */
function makeSource(feed_type: Source["feed_type"], extra?: Partial<Source>): Source {
  return {
    id: "src-dark-1",
    name: "Dark Feed",
    feed_type,
    url: "http://example.onion/",
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
    opsec_authorised: false,
    ...extra,
  };
}

/** Render SourceDialog in edit mode with a given Source.
 *  Edit mode locks the feed_type so the OPSEC banner is driven by initialSource.feed_type. */
function renderEdit(src: Source) {
  const onSubmit = vi.fn();
  const onClose = vi.fn();
  render(
    <SourceDialog
      open={true}
      mode="edit"
      initialSource={src}
      onSubmit={onSubmit}
      onClose={onClose}
    />,
  );
  return { onSubmit, onClose };
}

/** Render SourceDialog in add mode (defaults to feed_type='rss'). */
function renderAdd() {
  const onSubmit = vi.fn();
  const onClose = vi.fn();
  render(
    <SourceDialog
      open={true}
      mode="add"
      onSubmit={onSubmit}
      onClose={onClose}
    />,
  );
  return { onSubmit, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DarkwebOpsecWarning - SourceDialog OPSEC banner", () => {

  it("shows OPSEC warning for tor_html feed type", () => {
    renderEdit(makeSource("tor_html"));

    // The amber warning banner should be visible
    const warningText = OPSEC_WARNING_TEXT["tor_html"];
    expect(screen.getByText(warningText)).toBeInTheDocument();

    // The checkbox acknowledging risks should also be present
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
    expect(screen.getByText(/I understand the risks and authorise this source/i)).toBeInTheDocument();
  });

  it("shows type-specific OPSEC warning text for paste feed type", () => {
    renderEdit(makeSource("paste"));

    // The paste-specific warning text should be visible (not tor or telegram text)
    const pasteWarning = OPSEC_WARNING_TEXT["paste"];
    const torWarning = OPSEC_WARNING_TEXT["tor_html"];
    const telegramWarning = OPSEC_WARNING_TEXT["telegram"];

    expect(screen.getByText(pasteWarning)).toBeInTheDocument();
    expect(screen.queryByText(torWarning)).not.toBeInTheDocument();
    expect(screen.queryByText(telegramWarning)).not.toBeInTheDocument();
  });

  it("Save button is disabled when dark-web type selected but checkbox is unchecked", () => {
    renderEdit(makeSource("telegram", { opsec_authorised: false }));

    // The OPSEC banner should be visible
    const telegramWarning = OPSEC_WARNING_TEXT["telegram"];
    expect(screen.getByText(telegramWarning)).toBeInTheDocument();

    // Checkbox starts unchecked
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();

    // Save button must be disabled
    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    expect(saveBtn).toBeDisabled();
  });

  it("Save button becomes enabled after opsec_authorised checkbox is ticked", async () => {
    renderEdit(makeSource("tor_html", { opsec_authorised: false }));

    // Save button starts disabled
    const saveBtn = screen.getByRole("button", { name: /Save Changes/i });
    expect(saveBtn).toBeDisabled();

    // Tick the checkbox
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);

    // Save button should now be enabled
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Save Changes/i })).not.toBeDisabled();
    });
  });

  it("does NOT show OPSEC warning for clearnet feed types (rss default in add mode)", () => {
    renderAdd();

    // Default add mode uses feed_type='rss' - no OPSEC banner
    expect(screen.queryByText(/I understand the risks and authorise this source/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    // Save button should NOT be disabled by OPSEC gate (may still be disabled by empty form validation,
    // but the OPSEC gate specifically should not apply)
    // Verify none of the dark-web warning texts appear
    for (const text of Object.values(OPSEC_WARNING_TEXT)) {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    }
  });

});
