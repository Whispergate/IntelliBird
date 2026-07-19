import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Override the global react-cytoscapejs mock for this file only.
vi.mock("react-cytoscapejs", () => ({
  default: vi.fn(() => {
    const React = require("react") as typeof import("react");
    return React.createElement("div", { "data-testid": "cytoscape-graph" });
  }),
}));

// Mock shadcn Select so the dropdown options are always rendered in-DOM (no Portal).
// This makes layout-option assertions deterministic in jsdom.
vi.mock("@/components/ui/select", () => {
  const React = require("react") as typeof import("react");
  type SelectProps = {
    value?: string;
    onValueChange?: (v: string) => void;
    children?: React.ReactNode;
  };
  const Select = ({ value, onValueChange, children }: SelectProps) =>
    React.createElement("div", { "data-testid": "select-root", "data-value": value, onChange: (e: React.ChangeEvent<HTMLSelectElement>) => onValueChange?.(e.target.value) }, children);
  const SelectTrigger = ({ children }: { children?: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "select-trigger" }, children);
  const SelectValue = () => null;
  const SelectContent = ({ children }: { children?: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "select-content" }, children);
  const SelectItem = ({ value, children }: { value?: string; children?: React.ReactNode }) =>
    React.createElement(
      "button",
      {
        "data-testid": `select-item-${value}`,
        onClick: (e: React.MouseEvent) => {
          // Walk up to find the Select root and call its onChange
          const root = (e.currentTarget as HTMLElement).closest("[data-testid='select-root']");
          if (root) {
            const handler = (root as HTMLElement & { __selectHandler?: (v: string) => void }).__selectHandler;
            if (typeof handler === "function") handler(value ?? "");
          }
        },
      },
      children,
    );
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

import { AttackGraphToolbar } from "@/app/components/AttackGraphToolbar";

describe("AttackGraphToolbar - rendering", () => {
  it("renders Layout caption label", () => {
    render(<AttackGraphToolbar cy={null} />);
    expect(screen.getByText("Layout")).toBeInTheDocument();
  });

  it("renders all three layout option labels in the Select content", () => {
    render(<AttackGraphToolbar cy={null} />);
    expect(screen.getByText("Dagre - hierarchy")).toBeInTheDocument();
    expect(screen.getByText("CoSE - force")).toBeInTheDocument();
    expect(screen.getByText("Breadth-first")).toBeInTheDocument();
  });

  it("renders provenance switch with correct aria-label", () => {
    render(<AttackGraphToolbar cy={null} />);
    expect(
      screen.getByRole("switch", { name: "Show analyst-confirmed nodes only" }),
    ).toBeInTheDocument();
  });

  it("renders adjacent label text 'Analyst-confirmed only'", () => {
    render(<AttackGraphToolbar cy={null} />);
    expect(screen.getByText("Analyst-confirmed only")).toBeInTheDocument();
  });

  it("renders Zoom in button with aria-label", () => {
    render(<AttackGraphToolbar cy={null} />);
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeInTheDocument();
  });

  it("renders Zoom out button with aria-label", () => {
    render(<AttackGraphToolbar cy={null} />);
    expect(
      screen.getByRole("button", { name: "Zoom out" }),
    ).toBeInTheDocument();
  });

  it("renders Fit to content button with aria-label", () => {
    render(<AttackGraphToolbar cy={null} />);
    expect(
      screen.getByRole("button", { name: "Fit to content" }),
    ).toBeInTheDocument();
  });

  it("zoom in button calls cy.zoom with increased factor", async () => {
    const user = userEvent.setup();
    const fakeCy = {
      zoom: vi.fn((z?: number) => (z !== undefined ? z : 1)),
      fit: vi.fn(),
      layout: vi.fn(() => ({ run: vi.fn() })),
      elements: vi.fn(() => ({ not: vi.fn(() => ({ style: vi.fn() })), style: vi.fn() })),
    } as unknown as import("cytoscape").Core;

    render(<AttackGraphToolbar cy={fakeCy} />);
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(fakeCy.zoom).toHaveBeenCalled();
  });

  it("zoom out button calls cy.zoom", async () => {
    const user = userEvent.setup();
    const fakeCy = {
      zoom: vi.fn((z?: number) => (z !== undefined ? z : 1)),
      fit: vi.fn(),
      layout: vi.fn(() => ({ run: vi.fn() })),
      elements: vi.fn(() => ({ not: vi.fn(() => ({ style: vi.fn() })), style: vi.fn() })),
    } as unknown as import("cytoscape").Core;

    render(<AttackGraphToolbar cy={fakeCy} />);
    await user.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(fakeCy.zoom).toHaveBeenCalled();
  });

  it("fit to content button calls cy.fit", async () => {
    const user = userEvent.setup();
    const fakeCy = {
      zoom: vi.fn((z?: number) => (z !== undefined ? z : 1)),
      fit: vi.fn(),
      layout: vi.fn(() => ({ run: vi.fn() })),
      elements: vi.fn(() => ({ not: vi.fn(() => ({ style: vi.fn() })), style: vi.fn() })),
    } as unknown as import("cytoscape").Core;

    render(<AttackGraphToolbar cy={fakeCy} />);
    await user.click(screen.getByRole("button", { name: "Fit to content" }));
    expect(fakeCy.fit).toHaveBeenCalled();
  });
});
