/**
 * BrandTermDialog tests — plan 12-09 (UI-SPEC §Surface 6).
 *
 * Coverage:
 *   - RadioGroup renders all 4 term_type options
 *   - 'person' selection renders red-bordered GDPR block + required checkbox
 *   - Save disabled until consent checkbox ticked (person type)
 *   - Analyst (canCreatePerson=false) → person radio disabled with tooltip
 *   - Stoplist advisory appears for value in DEFAULT_STOPLIST ("core")
 *   - Short-term advisory appears for short non-stoplisted value ("api"? "core" is in stoplist)
 *       — use "xyzab" (5 chars, not in stoplist) to assert short-only path
 *   - onBlur fires preview; likely_too_broad warning renders
 *   - No labelled "Cancel" button; shadcn DialogPrimitive.Close X icon present
 *   - 409 surfaces in valueError useState with canonical copy
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
    info: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("../../lib/api", async () => {
  const actual =
    await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    createBrandTerm: vi.fn(),
    previewBrandTerm: vi.fn(),
  };
});

import { createBrandTerm, previewBrandTerm } from "../../lib/api";
import { BrandTermDialog } from "../BrandTermDialog";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BrandTermDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderOpen(
    overrides: Partial<React.ComponentProps<typeof BrandTermDialog>> = {},
  ) {
    return render(
      <BrandTermDialog
        open
        projectId="proj-1"
        onClose={() => {}}
        onCreated={() => {}}
        {...overrides}
      />,
    );
  }

  it("renders term_type RadioGroup with all 4 options", () => {
    renderOpen();
    for (const t of ["keyword", "domain", "product", "person"]) {
      expect(screen.getByLabelText(t)).toBeInTheDocument();
    }
  });

  it("selecting 'person' renders red-bordered GDPR block + required checkbox; submit blocked until consent", async () => {
    const user = userEvent.setup();
    renderOpen();

    await user.click(screen.getByLabelText("person"));

    // GDPR body copy
    expect(
      screen.getByText(
        /This term stores personal identifier data\./,
      ),
    ).toBeInTheDocument();
    // Checkbox label
    expect(
      screen.getByLabelText(
        "I confirm a lawful basis for processing this personal identifier.",
      ),
    ).toBeInTheDocument();
    // Red-bordered notice
    const notice = screen.getByRole("region", { name: "GDPR notice" });
    expect(notice.className).toMatch(/border-destructive/);

    // Fill value
    await user.type(screen.getByLabelText("Value"), "Jane Smith");

    // Submit button still disabled (consent unchecked)
    const submit = screen.getByRole("button", { name: /Add term/ });
    expect(submit).toBeDisabled();

    // Tick consent
    await user.click(
      screen.getByLabelText(
        "I confirm a lawful basis for processing this personal identifier.",
      ),
    );
    expect(submit).not.toBeDisabled();
  });

  it("disables 'person' radio with tooltip when canCreatePerson=false", async () => {
    renderOpen({ canCreatePerson: false });
    const personRadio = screen.getByLabelText("person");
    expect(personRadio).toBeDisabled();
    // Hover wrapper span to trigger Radix Tooltip portal
    const user = userEvent.setup();
    const wrapper = personRadio.closest("span");
    expect(wrapper).not.toBeNull();
    await user.hover(wrapper!);
    const tips = await screen.findAllByText(
      "Creating person-type terms requires Lead or Admin role — GDPR liability requires elevated authority.",
    );
    expect(tips.length).toBeGreaterThan(0);
  });

  it("stoplist advisory appears for value in DEFAULT_STOPLIST ('core')", async () => {
    const user = userEvent.setup();
    renderOpen();

    await user.type(screen.getByLabelText("Value"), "core");
    expect(
      screen.getByText(
        "This term is in the default stoplist. It will be accepted but flagged high_noise_risk.",
      ),
    ).toBeInTheDocument();
  });

  it("short-term advisory appears for short non-stoplisted value", async () => {
    const user = userEvent.setup();
    renderOpen();

    // 'xyzab' = 5 chars, not in stoplist
    await user.type(screen.getByLabelText("Value"), "xyzab");
    expect(
      screen.getByText(
        "Short terms may produce noisy matches. This term will be restricted to title/stix_id scan only.",
      ),
    ).toBeInTheDocument();
  });

  it("onBlur fires preview; warning block appears when likely_too_broad", async () => {
    vi.mocked(previewBrandTerm).mockResolvedValue({
      preview_matches: 860,
      percent: 86,
      warning: "likely_too_broad",
    });
    const user = userEvent.setup();
    renderOpen();

    const input = screen.getByLabelText("Value");
    await user.type(input, "company");
    await user.tab(); // blur

    await waitFor(() =>
      expect(vi.mocked(previewBrandTerm)).toHaveBeenCalledWith(
        "proj-1",
        "company",
        "keyword",
      ),
    );
    await waitFor(() =>
      expect(
        screen.getByText(
          "This term matches 860 of your last 1000 events (86%) — likely too broad.",
        ),
      ).toBeInTheDocument(),
    );
  });

  it("has no labelled 'Cancel' button; shadcn DialogPrimitive.Close X icon present", () => {
    renderOpen();
    // No button whose accessible name is "Cancel"
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();
    // shadcn Dialog's X close affordance carries sr-only "Close" label
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("409 from createBrandTerm surfaces valueError canonical copy", async () => {
    const err = new Error("conflict") as Error & { status?: number };
    err.status = 409;
    vi.mocked(createBrandTerm).mockRejectedValue(err);
    const user = userEvent.setup();
    renderOpen();

    await user.type(screen.getByLabelText("Value"), "IntelliBird");
    await user.click(screen.getByRole("button", { name: /Add term/ }));

    await waitFor(() =>
      expect(
        screen.getByText("This term already exists for this project."),
      ).toBeInTheDocument(),
    );
  });

  it("domain type zod error: 'Enter a valid domain name.'", async () => {
    const user = userEvent.setup();
    renderOpen();

    await user.click(screen.getByLabelText("domain"));
    await user.type(screen.getByLabelText("Value"), "not a domain");

    expect(
      screen.getByText("Enter a valid domain name."),
    ).toBeInTheDocument();
  });
});
