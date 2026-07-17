/**
 * ScanLaunchDialog tests
 *
 * Activates the Wave 0 stub from plan 11-00 / 11-08.
 * Covers UI-SPEC §Surface 4 + authority matrix + copywriting contract.
 */

import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock API helpers so no real HTTP calls are made
// ---------------------------------------------------------------------------
vi.mock("../lib/api", () => ({
  getSafelist: vi.fn(),
  launchScan: vi.fn(),
}));

// Mock next/navigation router
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

import { getSafelist, launchScan } from "../lib/api";
import { toast } from "sonner";
import { ScanLaunchDialog } from "../ScanLaunchDialog";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MOCK_SAFELIST = {
  modules: ["crt", "dnsdumpster", "shodan_dns", "urlscan", "wayback"],
  bbot_version: "2.8.4",
  requires_credentials: {},
};

const MOCK_SAFELIST_NO_SHODAN = {
  modules: ["crt", "dnsdumpster", "urlscan"],
  bbot_version: "2.8.4",
  requires_credentials: {},
};

const PROJECT_WITH_GATE: { active_scans_authorised: boolean; active_auth_confirmed_at: string } = {
  active_scans_authorised: true,
  active_auth_confirmed_at: new Date().toISOString(),
};

const PROJECT_NO_GATE = {
  active_scans_authorised: false,
  active_auth_confirmed_at: null,
};

function renderDialog(overrides: Partial<Parameters<typeof ScanLaunchDialog>[0]> = {}) {
  const defaults = {
    projectId: "proj-123",
    isOpen: true,
    onClose: vi.fn(),
    project: PROJECT_WITH_GATE,
    userCanLaunchActive: true,
    onLaunched: vi.fn(),
  };
  return render(<ScanLaunchDialog {...defaults} {...overrides} />);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ScanLaunchDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSafelist).mockResolvedValue(MOCK_SAFELIST);
    vi.mocked(launchScan).mockResolvedValue({
      id: "scan-1",
      project_id: "proj-123",
      status: "queued",
      scan_mode: "passive",
      modules: [],
      started_at: new Date().toISOString(),
      finished_at: null,
      stdout_bytes: 0,
      error: null,
      launched_by: "user-sub",
      findings_count: 0,
    });
  });

  it("renders dialog title 'Launch EASM Scan'", async () => {
    renderDialog();
    expect(await screen.findByText("Launch EASM Scan")).toBeInTheDocument();
  });

  it("passive radio is selected by default", async () => {
    renderDialog();
    // Wait for safelist to load
    await screen.findByText("crt");
    const passiveRadio = screen.getByRole("radio", { name: /passive/i });
    expect(passiveRadio).toBeChecked();
  });

  it("active radio is disabled when gate not set; tooltip copy matches UI-SPEC", async () => {
    renderDialog({ project: PROJECT_NO_GATE, userCanLaunchActive: true });
    await screen.findByText("crt");
    const activeRadio = screen.getByRole("radio", { name: /active/i });
    expect(activeRadio).toBeDisabled();
    // The tooltip copy appears in the disabled label
    expect(
      screen.getByText(
        "Active scans require active-scan authorisation. Set it on the Settings tab.",
      ),
    ).toBeInTheDocument();
  });

  it("active radio is disabled when userCanLaunchActive=false; tooltip copy matches", async () => {
    renderDialog({ userCanLaunchActive: false, project: PROJECT_WITH_GATE });
    await screen.findByText("crt");
    const activeRadio = screen.getByRole("radio", { name: /active/i });
    expect(activeRadio).toBeDisabled();
    expect(
      screen.getByText(
        "Only project Leads and global Admins may launch active scans.",
      ),
    ).toBeInTheDocument();
  });

  it("active radio is enabled when gate is set AND user has authority", async () => {
    renderDialog({ project: PROJECT_WITH_GATE, userCanLaunchActive: true });
    await screen.findByText("crt");
    const activeRadio = screen.getByRole("radio", { name: /active/i });
    expect(activeRadio).not.toBeDisabled();
  });

  it("module list is populated from mocked getSafelist response", async () => {
    renderDialog();
    await screen.findByText("crt");
    expect(screen.getByText("dnsdumpster")).toBeInTheDocument();
    expect(screen.getByText("shodan_dns")).toBeInTheDocument();
    expect(screen.getByText("urlscan")).toBeInTheDocument();
    expect(screen.getByText("wayback")).toBeInTheDocument();
  });

  it("shodan note shown when shodan_dns is in safelist", async () => {
    renderDialog();
    await screen.findByText("shodan_dns");
    expect(
      screen.getByText(
        "Shodan API key optional — enables shodan_dns. Without it, shodan_dns is skipped and the scan continues.",
      ),
    ).toBeInTheDocument();
  });

  it("shodan note hidden when shodan_dns is absent from safelist", async () => {
    vi.mocked(getSafelist).mockResolvedValue(MOCK_SAFELIST_NO_SHODAN);
    renderDialog();
    await screen.findByText("crt");
    expect(
      screen.queryByText(/Shodan API key optional/),
    ).not.toBeInTheDocument();
  });

  it("submit is disabled when no modules are checked", async () => {
    renderDialog();
    await screen.findByText("crt");
    // Click each checked checkbox once to uncheck it
    const checkboxes = screen.getAllByRole("checkbox");
    for (const checkbox of checkboxes) {
      if (checkbox.getAttribute("data-state") === "checked") {
        fireEvent.click(checkbox);
      }
    }
    // Wait for state update then verify
    await waitFor(() => {
      const submitBtn = screen.getByRole("button", { name: /launch passive scan/i });
      expect(submitBtn).toBeDisabled();
    });
  });

  it("submit button label is 'Launch passive scan' in passive mode", async () => {
    renderDialog();
    await screen.findByText("crt");
    expect(
      screen.getByRole("button", { name: "Launch passive scan" }),
    ).toBeInTheDocument();
  });

  it("submit button label is 'Launch active scan' when active mode selected", async () => {
    renderDialog({ project: PROJECT_WITH_GATE, userCanLaunchActive: true });
    await screen.findByText("crt");
    const activeRadio = screen.getByRole("radio", { name: /active/i });
    fireEvent.click(activeRadio);
    expect(
      screen.getByRole("button", { name: "Launch active scan" }),
    ).toBeInTheDocument();
  });

  it("error 503 triggers byte-exact toast copy", async () => {
    const err = Object.assign(new Error("503 Service Unavailable"), { status: 503 });
    vi.mocked(launchScan).mockRejectedValue(err);
    renderDialog();
    await screen.findByText("crt");
    const submitBtn = screen.getByRole("button", { name: /launch passive scan/i });
    fireEvent.click(submitBtn);
    await waitFor(() => {
      expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
        "Scan limit reached. Wait for a running scan to finish before launching another.",
      );
    });
  });

  it("error 422 with module names triggers byte-exact toast copy", async () => {
    const err = Object.assign(
      new Error("422: invalid_modules: shodan_dns,crt"),
      { status: 422 },
    );
    vi.mocked(launchScan).mockRejectedValue(err);
    renderDialog();
    await screen.findByText("crt");
    const submitBtn = screen.getByRole("button", { name: /launch passive scan/i });
    fireEvent.click(submitBtn);
    await waitFor(() => {
      expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
        expect.stringContaining(
          "One or more selected modules are not in the stable safelist:",
        ),
      );
    });
  });
});
