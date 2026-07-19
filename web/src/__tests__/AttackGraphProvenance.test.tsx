import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

// Override the global react-cytoscapejs mock for this file only.
vi.mock("react-cytoscapejs", () => ({
  default: vi.fn(() => {
    const React = require("react") as typeof import("react");
    return React.createElement("div", { "data-testid": "cytoscape-graph" });
  }),
}));

// Capture the onValueChange callback so tests can fire layout changes directly.
let capturedOnValueChange: ((v: string) => void) | null = null;

vi.mock("@/components/ui/select", () => {
  const React = require("react") as typeof import("react");
  type SelectProps = {
    value?: string;
    onValueChange?: (v: string) => void;
    children?: React.ReactNode;
  };
  const Select = ({ value, onValueChange, children }: SelectProps) => {
    capturedOnValueChange = onValueChange ?? null;
    return React.createElement(
      "div",
      { "data-testid": "select-root", "data-value": value },
      children,
    );
  };
  const SelectTrigger = ({ children }: { children?: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "select-trigger" }, children);
  const SelectValue = ({ placeholder }: { placeholder?: string }) =>
    React.createElement("span", null, placeholder ?? null);
  const SelectContent = ({ children }: { children?: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "select-content" }, children);
  const SelectItem = ({ value, children }: { value?: string; children?: React.ReactNode }) =>
    React.createElement(
      "button",
      { "data-testid": `select-item-${value}`, "data-value": value },
      children,
    );
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

import { AttackGraphToolbar } from "@/app/components/AttackGraphToolbar";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeFakeCy() {
  const notStyleMock = vi.fn();
  const notMock = vi.fn(() => ({ style: notStyleMock }));
  const elementsStyleMock = vi.fn();
  const elementsMock = vi.fn(() => ({
    not: notMock,
    style: elementsStyleMock,
  }));
  const runMock = vi.fn();
  const layoutMock = vi.fn(() => ({ run: runMock }));
  const fitMock = vi.fn();
  const zoomMock = vi.fn((z?: number) => (z !== undefined ? z : 1));

  return {
    cy: {
      zoom: zoomMock,
      fit: fitMock,
      layout: layoutMock,
      elements: elementsMock,
    } as unknown as import("cytoscape").Core,
    mocks: {
      notStyleMock,
      notMock,
      elementsStyleMock,
      elementsMock,
      runMock,
      layoutMock,
      fitMock,
      zoomMock,
    },
  };
}

beforeEach(() => {
  window.sessionStorage.clear();
  capturedOnValueChange = null;
});

// ── sessionStorage tests ──────────────────────────────────────────────────────

describe("AttackGraphToolbar - sessionStorage / layout persistence", () => {
  it("reads layout from sessionStorage on mount - Select receives persisted value", () => {
    window.sessionStorage.setItem("intellibird:graph-layout", "cose");
    render(<AttackGraphToolbar cy={null} />);
    // The Select mock renders with data-value reflecting what was passed in
    const selectRoot = screen.getByTestId("select-root");
    expect(selectRoot.getAttribute("data-value")).toBe("cose");
  });

  it("falls back to 'dagre' when sessionStorage is empty", () => {
    render(<AttackGraphToolbar cy={null} />);
    const selectRoot = screen.getByTestId("select-root");
    expect(selectRoot.getAttribute("data-value")).toBe("dagre");
  });

  it("writes the selected layout to sessionStorage under intellibird:graph-layout", () => {
    render(<AttackGraphToolbar cy={null} />);

    // Fire the onValueChange directly (simulates user selecting from the dropdown)
    expect(capturedOnValueChange).not.toBeNull();
    act(() => {
      capturedOnValueChange!("breadthfirst");
    });

    // Assert the value was actually persisted (read-back is more reliable than spy in jsdom)
    expect(window.sessionStorage.getItem("intellibird:graph-layout")).toBe(
      "breadthfirst",
    );
  });

  it("changing layout invokes cy.layout().run() and cy.fit()", () => {
    const { cy, mocks } = makeFakeCy();
    render(<AttackGraphToolbar cy={cy} />);

    expect(capturedOnValueChange).not.toBeNull();
    act(() => { capturedOnValueChange!("breadthfirst"); });

    expect(mocks.layoutMock).toHaveBeenCalledWith(
      expect.objectContaining({ name: "breadthfirst" }),
    );
    expect(mocks.runMock).toHaveBeenCalled();
    expect(mocks.fitMock).toHaveBeenCalled();
  });

  it("changing layout to cose passes correct cose config to cy.layout()", () => {
    const { cy, mocks } = makeFakeCy();
    render(<AttackGraphToolbar cy={cy} />);

    act(() => { capturedOnValueChange!("cose"); });

    expect(mocks.layoutMock).toHaveBeenCalledWith(
      expect.objectContaining({ name: "cose", animate: true }),
    );
    expect(mocks.runMock).toHaveBeenCalled();
    expect(mocks.fitMock).toHaveBeenCalled();
  });
});

// ── Provenance toggle tests ──────────────────────────────────────────────────

describe("AttackGraphToolbar - provenance toggle", () => {
  it("does not call cy.elements on initial render (provenance off by default)", () => {
    const { cy, mocks } = makeFakeCy();
    render(<AttackGraphToolbar cy={cy} />);
    expect(mocks.elementsMock).not.toHaveBeenCalled();
  });

  it("toggling on hides non-analyst nodes via cy.elements().not(...).style('display','none')", async () => {
    const user = userEvent.setup();
    const { cy, mocks } = makeFakeCy();

    render(<AttackGraphToolbar cy={cy} />);
    const sw = screen.getByRole("switch", {
      name: "Show analyst-confirmed nodes only",
    });
    await user.click(sw);

    expect(mocks.elementsMock).toHaveBeenCalled();
    expect(mocks.notMock).toHaveBeenCalledWith("[tag_source = 'analyst']");
    expect(mocks.notStyleMock).toHaveBeenCalledWith("display", "none");
    expect(mocks.fitMock).toHaveBeenCalled();
  });

  it("toggling off restores all nodes via cy.elements().style('display','element')", async () => {
    const user = userEvent.setup();
    const { cy, mocks } = makeFakeCy();

    render(<AttackGraphToolbar cy={cy} />);
    const sw = screen.getByRole("switch", {
      name: "Show analyst-confirmed nodes only",
    });

    // Toggle on then off
    await user.click(sw);
    await user.click(sw);

    expect(mocks.elementsStyleMock).toHaveBeenCalledWith("display", "element");
    expect(mocks.fitMock).toHaveBeenCalledTimes(2);
  });

  it("provenance toggle state is NOT persisted to sessionStorage", async () => {
    const user = userEvent.setup();

    render(<AttackGraphToolbar cy={null} />);
    const sw = screen.getByRole("switch", {
      name: "Show analyst-confirmed nodes only",
    });
    await user.click(sw);

    // No provenance key should have been written
    const keys = Object.keys(window.sessionStorage);
    const provenanceKeys = keys.filter(
      (k) => k.includes("provenance") || k.includes("analyst"),
    );
    expect(provenanceKeys).toHaveLength(0);
    // Only the layout key (if any) may exist; confirm no provenance storage
    expect(window.sessionStorage.getItem("intellibird:graph-layout-provenance")).toBeNull();
  });

  it("remounting toolbar shows provenance switch as off by default", () => {
    const { unmount } = render(<AttackGraphToolbar cy={null} />);
    const sw = screen.getByRole("switch", {
      name: "Show analyst-confirmed nodes only",
    });
    expect(sw).not.toBeChecked();
    unmount();

    render(<AttackGraphToolbar cy={null} />);
    const sw2 = screen.getByRole("switch", {
      name: "Show analyst-confirmed nodes only",
    });
    expect(sw2).not.toBeChecked();
  });

  it("intellibird:graph-layout key is used for sessionStorage (not a different key)", () => {
    render(<AttackGraphToolbar cy={null} />);
    act(() => { capturedOnValueChange!("cose"); });
    // Verify the exact key
    expect(window.sessionStorage.getItem("intellibird:graph-layout")).toBe("cose");
  });
});
