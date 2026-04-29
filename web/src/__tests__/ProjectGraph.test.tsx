/**
 * ProjectGraph.test.tsx — Phase 20-03 (GRAPH-01 frontend)
 *
 * Tests that ProjectGraph renders:
 * 1. Empty state when zero events (no nodes, no edges)
 * 2. No-relationships state when nodes > 0 but edges = 0
 * 3. Cytoscape container when both nodes and edges present
 * 4. Truncate banner when data.truncated = true
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProjectGraph } from "@/app/projects/[id]/graph/ProjectGraph";

// react-cytoscapejs is globally mocked in vitest.setup.ts to render
// <div data-testid="cytoscape-graph" />. This file adds a per-file override
// so the mock element carries the container's data-testid through.
// The global mock in setup.ts is sufficient — we just import and use it.

const emptyData = { nodes: [], edges: [], truncated: false };

const nodesOnlyData = {
  nodes: [{ id: "n1", label: "Event A", node_type: "event" }],
  edges: [],
  truncated: false,
};

const populatedData = {
  nodes: [
    { id: "n1", label: "Event A", node_type: "event" },
    { id: "n2", label: "T1190", node_type: "technique" },
  ],
  edges: [{ source: "n1", target: "n2", relation: "technique" }],
  truncated: false,
};

const truncatedData = {
  nodes: [
    { id: "n1", label: "Event A", node_type: "event" },
    { id: "n2", label: "T1190", node_type: "technique" },
  ],
  edges: [{ source: "n1", target: "n2", relation: "technique" }],
  truncated: true,
};

describe("ProjectGraph", () => {
  it("renders empty state CTAs when zero events", () => {
    render(<ProjectGraph data={emptyData} projectId="p1" />);
    expect(
      screen.getByText(/no project events yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /manage scope/i }),
    ).toBeInTheDocument();
  });

  it("renders no-relationships state when nodes > 0 but edges = 0", () => {
    render(<ProjectGraph data={nodesOnlyData} projectId="p1" />);
    expect(
      screen.getByText(/no graph relationships yet/i),
    ).toBeInTheDocument();
  });

  it("renders graph container when nodes and edges are populated", () => {
    render(<ProjectGraph data={populatedData} projectId="p1" />);
    expect(
      screen.getByTestId("project-graph-container"),
    ).toBeInTheDocument();
  });

  it("renders truncate banner when truncated=true", () => {
    render(<ProjectGraph data={truncatedData} projectId="p1" />);
    expect(
      screen.getByTestId("graph-truncate-banner"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("graph-truncate-banner").textContent,
    ).toMatch(/narrow scope/i);
  });
});
