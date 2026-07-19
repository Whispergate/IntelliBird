// Owned by: 12.1-06-PLAN
// ProjectTabs - assert 16-tab strip with Assets at position 15 (between EASM and Brand).

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProjectTabs } from "@/app/projects/[id]/ProjectTabs";

const pushMock = vi.fn();
const replaceMock = vi.fn();
let pathnameMock = "/projects/abc";
let searchParamsMock = new URLSearchParams("");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  usePathname: () => pathnameMock,
  useSearchParams: () => searchParamsMock,
}));

beforeEach(() => {
  pushMock.mockClear();
  replaceMock.mockClear();
  pathnameMock = "/projects/abc";
  searchParamsMock = new URLSearchParams("");
});

// Helper: read the visible tab labels in DOM order.
function getTabLabels(): string[] {
  return screen
    .getAllByRole("tab")
    .map((el) => (el.textContent ?? "").trim());
}

describe("ProjectTabs (-06)", => {
  it("renders 16 tabs with Assets at position 15, between EASM (14) and Brand (16)", () => {
    render(<ProjectTabs projectId="abc" projectName="Acme" />);
    const labels = getTabLabels();
    expect(labels).toHaveLength(16);
    expect(labels[13]).toBe("EASM"); // position 14 (0-indexed 13)
    expect(labels[14]).toBe("Assets"); // position 15
    expect(labels[15]).toBe("Brand"); // position 16
  });

  it("Assets tab is active on /projects/[id]/assets", () => {
    pathnameMock = "/projects/abc/assets";
    render(<ProjectTabs projectId="abc" projectName="Acme" />);
    const assetsTab = screen.getByRole("tab", { name: "Assets" });
    expect(assetsTab.getAttribute("data-state")).toBe("active");
  });

  it("Assets tab stays active on sub-paths under /assets", () => {
    pathnameMock = "/projects/abc/assets/some-asset-id";
    render(<ProjectTabs projectId="abc" projectName="Acme" />);
    const assetsTab = screen.getByRole("tab", { name: "Assets" });
    expect(assetsTab.getAttribute("data-state")).toBe("active");
  });

  it("Brand tab remains active on /brand paths (no /assets confusion)", () => {
    pathnameMock = "/projects/abc/brand";
    render(<ProjectTabs projectId="abc" projectName="Acme" />);
    const brandTab = screen.getByRole("tab", { name: "Brand" });
    expect(brandTab.getAttribute("data-state")).toBe("active");
    const assetsTab = screen.getByRole("tab", { name: "Assets" });
    expect(assetsTab.getAttribute("data-state")).not.toBe("active");
  });

  it("clicking Assets navigates to /projects/{id}/assets via router.push", async () => {
    render(<ProjectTabs projectId="abc" projectName="Acme" />);
    await userEvent.click(screen.getByRole("tab", { name: "Assets" }));
    expect(pushMock).toHaveBeenCalledWith("/projects/abc/assets");
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
