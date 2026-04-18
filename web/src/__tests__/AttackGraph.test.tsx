import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// ── Per-file react-cytoscapejs override ────────────────────────────────────
// Captures the stylesheet prop so we can assert NODE_STYLES contents.
const renderMock = vi.fn();
vi.mock("react-cytoscapejs", () => ({
  default: (props: { style?: React.CSSProperties; stylesheet?: unknown[] }) => {
    renderMock(props);
    const React = require("react") as typeof import("react");
    return React.createElement("div", {
      "data-testid": "cytoscape-graph",
      style: props.style,
    });
  },
}));

vi.mock("@/app/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/app/api-client")>(
    "@/app/api-client",
  );
  return { ...actual, getEventGraph: vi.fn() };
});

import { getEventGraph } from "@/app/api-client";
import { AttackGraphImpl } from "@/app/components/AttackGraphImpl";
import { RoleProvider } from "@/app/lib/role-context";

const getEventGraphMock = vi.mocked(getEventGraph);

beforeEach(() => {
  getEventGraphMock.mockReset();
  renderMock.mockReset();
});

describe("AttackGraph", () => {
  it("shows loading skeleton while fetch is pending", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let resolve: (v: any) => void = () => {};
    getEventGraphMock.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    render(
      <RoleProvider value="blue">
        <AttackGraphImpl eventId="evt-1" />
      </RoleProvider>,
    );
    expect(screen.getByTestId("attack-graph-loading")).toBeInTheDocument();
    resolve({ nodes: [], edges: [], truncated: false });
  });

  it("renders 'No graph data for this event.' when nodes empty", async () => {
    getEventGraphMock.mockResolvedValueOnce({
      nodes: [],
      edges: [],
      truncated: false,
    });
    render(
      <RoleProvider value="blue">
        <AttackGraphImpl eventId="evt-1" />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(
        screen.getByText("No graph data for this event."),
      ).toBeInTheDocument();
    });
  });

  it("renders cytoscape placeholder (from vitest mock) when nodes present", async () => {
    getEventGraphMock.mockResolvedValueOnce({
      nodes: [
        { data: { id: "n1", label: "Event A", type: "event" } },
        { data: { id: "n2", label: "T1190", type: "technique" } },
      ],
      edges: [
        { data: { source: "n1", target: "n2", relation: "technique" } },
      ],
      truncated: false,
    });
    render(
      <RoleProvider value="blue">
        <AttackGraphImpl eventId="evt-1" />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument();
    });
  });

  it("getEventGraph called with role from context", async () => {
    getEventGraphMock.mockResolvedValueOnce({
      nodes: [],
      edges: [],
      truncated: false,
    });
    render(
      <RoleProvider value="red">
        <AttackGraphImpl eventId="evt-9" />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(getEventGraphMock).toHaveBeenCalledWith("evt-9", 2, "red");
    });
  });

  it("renders 'Graph unavailable.' on fetch error", async () => {
    getEventGraphMock.mockRejectedValueOnce(new Error("boom"));
    render(
      <RoleProvider value="blue">
        <AttackGraphImpl eventId="evt-1" />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("Graph unavailable.")).toBeInTheDocument();
    });
  });

  // ── Phase 6 stylesheet assertions ─────────────────────────────────────────

  it("technique node has hexagon shape selector in NODE_STYLES", async () => {
    getEventGraphMock.mockResolvedValueOnce({
      nodes: [
        {
          data: {
            id: "n1",
            label: "T1190",
            type: "technique",
            tag_source: "analyst",
          },
        },
      ],
      edges: [],
      truncated: false,
    });
    render(
      <RoleProvider value="blue">
        <AttackGraphImpl eventId="evt-1" />
      </RoleProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument(),
    );

    const stylesheet = renderMock.mock.calls[0][0]
      .stylesheet as Array<{ selector: string; style: Record<string, unknown> }>;
    const entry = stylesheet.find(
      (e) => e.selector === "node[type='technique']" && e.style.shape === "hexagon",
    );
    expect(entry).toBeDefined();
  });

  it("analyst tag_source has solid border-style selector in NODE_STYLES", async () => {
    getEventGraphMock.mockResolvedValueOnce({
      nodes: [
        {
          data: {
            id: "n1",
            label: "T1059",
            type: "technique",
            tag_source: "analyst",
          },
        },
      ],
      edges: [],
      truncated: false,
    });
    render(
      <RoleProvider value="blue">
        <AttackGraphImpl eventId="evt-2" />
      </RoleProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument(),
    );

    const stylesheet = renderMock.mock.calls[0][0]
      .stylesheet as Array<{ selector: string; style: Record<string, unknown> }>;
    const entry = stylesheet.find(
      (e) =>
        e.selector === "node[tag_source='analyst']" &&
        e.style["border-style"] === "solid",
    );
    expect(entry).toBeDefined();
  });

  it("infrastructure node has fill #0F6E56 in NODE_STYLES", async () => {
    getEventGraphMock.mockResolvedValueOnce({
      nodes: [
        {
          data: {
            id: "n1",
            label: "Infra",
            type: "infrastructure",
            tag_source: "feed_asserted",
          },
        },
      ],
      edges: [],
      truncated: false,
    });
    render(
      <RoleProvider value="blue">
        <AttackGraphImpl eventId="evt-3" />
      </RoleProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("cytoscape-graph")).toBeInTheDocument(),
    );

    const stylesheet = renderMock.mock.calls[0][0]
      .stylesheet as Array<{ selector: string; style: Record<string, unknown> }>;
    const entry = stylesheet.find(
      (e) =>
        e.selector === "node[type='infrastructure']" &&
        e.style["background-color"] === "#0F6E56",
    );
    expect(entry).toBeDefined();
  });
});
