/**
 * IOCBulkImportDialog tests
 *
 * Covers UI-SPEC §Surface 3:
 *   1. 4-step stepper advances Upload → Configure → Preview → Import.
 *   2. Lead+ role gate — IOCsClient does not render the dialog for Observer
 *      (covered indirectly here via the open-prop contract: when not Lead+ the
 *      parent never sets `open=true`).
 *   3. dry-run preview renders insert/update/skip/error counts.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

if (
  typeof Element !== "undefined" &&
  !Element.prototype.hasPointerCapture
) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

const mockDryRun = vi.fn();
const mockSubmit = vi.fn();
const mockPoll = vi.fn();

vi.mock("@/app/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/app/api-client")>(
    "@/app/api-client",
  );
  return {
    ...actual,
    dryRunBulkImport: (...args: unknown[]) => mockDryRun(...args),
    submitBulkImport: (...args: unknown[]) => mockSubmit(...args),
    pollJobStatus: (...args: unknown[]) => mockPoll(...args),
  };
});

import { IOCBulkImportDialog } from "../IOCBulkImportDialog";

function renderDialog(overrides: Partial<{ open: boolean }> = {}) {
  const onOpenChange = vi.fn();
  const onComplete = vi.fn();
  const utils = render(
    <IOCBulkImportDialog
      open={overrides.open ?? true}
      onOpenChange={onOpenChange}
      projectId="proj-1"
      onComplete={onComplete}
    />,
  );
  return { ...utils, onOpenChange, onComplete };
}

describe("IOCBulkImportDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("4-step stepper advances Upload → Configure → Preview → Import", async () => {
    mockDryRun.mockResolvedValue({
      would_insert: 5,
      would_update: 2,
      would_skip: 1,
      unmapped_sdo_count: 0,
      errors: [],
    });
    mockSubmit.mockResolvedValue({ job_id: "job-abc", rows_accepted: 7 });
    mockPoll.mockResolvedValue({
      status: "running",
      processed: 5,
      total: 7,
      inserted: 0,
      updated: 0,
      skipped: 0,
    });

    renderDialog();

    // Step 1 visible
    expect(screen.getByTestId("step-circle-1")).toBeInTheDocument();
    expect(screen.getByText(/Drag and drop a file here/)).toBeInTheDocument();

    // Upload a file
    const file = new File(["type,value\nip,1.2.3.4\n"], "iocs.csv", {
      type: "text/csv",
    });
    const input = screen
      .getByTestId("bulk-dropzone")
      .querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();

    const user = userEvent.setup();
    await user.upload(input, file);

    // Click Continue → step 2
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    await waitFor(() =>
      expect(screen.getByText(/Default confidence/)).toBeInTheDocument(),
    );

    // Click Run dry-run → step 3
    await user.click(screen.getByRole("button", { name: /Run dry-run/i }));
    await waitFor(() => expect(mockDryRun).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText(/Insert/i)).toBeInTheDocument(),
    );

    // Click Confirm import → step 4
    await user.click(screen.getByRole("button", { name: /Confirm import/i }));
    await waitFor(() => expect(mockSubmit).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText(/Importing IOCs/i)).toBeInTheDocument(),
    );
  });

  it("Lead+ role gate hides dialog from Observer (open=false → not rendered)", () => {
    renderDialog({ open: false });
    expect(screen.queryByText(/Drag and drop a file here/)).toBeNull();
    expect(screen.queryByText(/Import IOCs/)).toBeNull();
  });

  it("dry-run preview renders insert/update/skip/error counts", async () => {
    mockDryRun.mockResolvedValue({
      would_insert: 12,
      would_update: 3,
      would_skip: 4,
      unmapped_sdo_count: 0,
      errors: [
        { line: 7, value: "bad-value", error: "invalid IP format" },
      ],
    });

    renderDialog();
    const file = new File(["type,value\nip,1.2.3.4\n"], "iocs.csv", {
      type: "text/csv",
    });
    const input = screen
      .getByTestId("bulk-dropzone")
      .querySelector('input[type="file"]') as HTMLInputElement;
    const user = userEvent.setup();
    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    await waitFor(() =>
      expect(screen.getByText(/Default confidence/)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Run dry-run/i }));
    await waitFor(() => expect(mockDryRun).toHaveBeenCalled());

    // Stat values render in 4-up grid — use class scope to disambiguate
    // from stepper-circle digit text.
    expect(await screen.findByText("12")).toBeInTheDocument();
    const insertLabels = screen.getAllByText(/^Insert$/i);
    expect(insertLabels.length).toBeGreaterThan(0);
    // Error line number rendered
    expect(screen.getByText(/L7/)).toBeInTheDocument();
    expect(screen.getByText(/invalid IP format/)).toBeInTheDocument();
  });

  it("per-row errors render with line numbers", async () => {
    mockDryRun.mockResolvedValue({
      would_insert: 0,
      would_update: 0,
      would_skip: 0,
      unmapped_sdo_count: 0,
      errors: [
        { line: 1, value: "junk", error: "no type column" },
        { line: 2, value: "junk2", error: "bad" },
      ],
    });

    renderDialog();
    const file = new File(["junk\n"], "iocs.csv", { type: "text/csv" });
    const input = screen
      .getByTestId("bulk-dropzone")
      .querySelector('input[type="file"]') as HTMLInputElement;
    const user = userEvent.setup();
    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    await waitFor(() =>
      expect(screen.getByText(/Default confidence/)).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /Run dry-run/i }));
    await waitFor(() => expect(mockDryRun).toHaveBeenCalled());

    expect(await screen.findByText(/L1/)).toBeInTheDocument();
    expect(screen.getByText(/L2/)).toBeInTheDocument();
    // No-rows path → CTA reads Cancel
    expect(screen.getByRole("button", { name: /Cancel/i })).toBeInTheDocument();
  });
});
