"use client";

import { useEffect, useRef, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import Cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import contextMenus from "cytoscape-context-menus";
// Note: cytoscape-context-menus CSS imported in globals.css, NOT here

import {
  getEventGraph,
  traverseGraph,
  type GraphResponse,
  type TraverseGraphResponse,
} from "@/app/api-client";
import { useRole } from "@/app/lib/role-context";
import { AttackGraphToolbar } from "@/app/components/AttackGraphToolbar";

// Guard against double registration if AttackGraph is mounted more than once.
let dagreRegistered = false;
if (!dagreRegistered) {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (Cytoscape as any).use(dagre);
    dagreRegistered = true;
  } catch {
    // Plugin already registered — ignore.
  }
}

let contextMenusRegistered = false;
if (!contextMenusRegistered) {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (Cytoscape as any).use(contextMenus);
    contextMenusRegistered = true;
  } catch {
    // Plugin already registered — ignore.
  }
}

const NODE_STYLES = [
  // ── Per-type fill colors ──────────────────────────────────────
  {
    selector: "node[type='event']",
    style: {
      "background-color": "#1D9E75",
      "border-color": "#0F6E56",
      "border-width": 1,
      color: "#E1F5EE",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 24,
      height: 24,
    },
  },
  {
    selector: "node[type='technique']",
    style: {
      "background-color": "#0F6E56",
      "border-color": "#9FE1CB",
      "border-width": 1,
      color: "#9FE1CB",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 22,
      height: 22,
    },
  },
  {
    selector: "node[type='actor']",
    style: {
      "background-color": "hsl(0, 70%, 45%)",
      "border-color": "hsl(0, 70%, 45%)",
      color: "#E1F5EE",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 24,
      height: 24,
    },
  },
  {
    selector: "node[type='malware']",
    style: {
      "background-color": "hsl(0, 50%, 35%)",
      "border-color": "hsl(0, 70%, 45%)",
      color: "#E1F5EE",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
    },
  },
  {
    selector: "node[type='campaign']",
    style: {
      "background-color": "#888780",
      "border-color": "#9FE1CB",
      color: "#E1F5EE",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
    },
  },
  // ── Infrastructure node type ─────────────────
  {
    selector: "node[type='infrastructure']",
    style: {
      "background-color": "#0F6E56",
      "border-color": "#888780",
      color: "#E1F5EE",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 22,
      height: 22,
    },
  },
  // ── Edges ──────────────────────────────────────────────────────
  {
    selector: "edge",
    style: {
      "line-color": "#0F6E56",
      "target-arrow-color": "#0F6E56",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      width: 1,
    },
  },
  // ── Node shape encoding ────────────────────────────────
  // MUST appear after per-type fill entries so specificity order is correct.
  {
    selector: "node[type='event']",
    style: { shape: "round-rectangle" },
  },
  {
    selector: "node[type='technique']",
    style: { shape: "hexagon" },
  },
  {
    selector: "node[type='actor']",
    style: { shape: "diamond" },
  },
  {
    selector: "node[type='malware']",
    style: { shape: "triangle" },
  },
  {
    selector: "node[type='campaign']",
    style: { shape: "ellipse" },
  },
  {
    selector: "node[type='infrastructure']",
    style: { shape: "square" },
  },
  // ── Provenance border-style encoding ───────────────────
  // MUST appear AFTER the shape selectors ( — order matters).
  {
    selector: "node[tag_source='analyst']",
    style: { "border-style": "solid", "border-width": 2, "border-opacity": 1.0 },
  },
  {
    selector: "node[tag_source='feed_asserted']",
    style: { "border-style": "dashed", "border-width": 2, "border-opacity": 1.0 },
  },
  {
    selector: "node[tag_source='auto']",
    style: { "border-style": "dashed", "border-width": 2, "border-opacity": 0.5 },
  },
  // ── DomainPivot node (Phase 28) ─────────────────────────────────
  {
    selector: "node[type='domain_pivot']",
    style: {
      "background-color": "#7C3AED",
      "border-color": "#A78BFA",
      "border-width": 2,
      color: "#F5F3FF",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      shape: "diamond",
      width: 28,
      height: 28,
    },
  },
  // ── Shares-infra edge (Phase 28) ─────────────────────────────────
  {
    selector: "edge[relation='shares_infra']",
    style: {
      "line-color": "#7C3AED",
      "target-arrow-color": "#7C3AED",
      "line-style": "dashed",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      width: 1,
    },
  },
];

export function AttackGraphImpl({
  eventId,
  height = 240,
  projectId,
}: {
  eventId: string;
  height?: number;
  /** Optional project UUID — enables multi-hop expand via right-click context menu. */
  projectId?: string | null;
}) {
  const role = useRole();
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const cyRef = useRef<Cytoscape.Core | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    getEventGraph(eventId, 2, role)
      .then((g) => {
        if (!cancelled) {
          setGraph(g);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [eventId, role]);

  /**
   * Expand a node N hops via the AGE traverse endpoint (Phase 28 / GRAPH-02).
   * Appends new nodes/edges without a full re-render.
   */
  const handleExpand = async (nodeId: string, hops: 1 | 2 | 3) => {
    const cy = cyRef.current;
    if (!cy || !projectId) return;
    try {
      const data: TraverseGraphResponse = await traverseGraph(projectId, nodeId, hops);
      const existingIds = new Set(cy.elements().map((el) => el.id()));
      const newElements: Cytoscape.ElementDefinition[] = [];
      for (const node of data.nodes) {
        if (!existingIds.has(node.data.id)) {
          newElements.push({ data: node.data });
        }
      }
      for (const edge of data.edges) {
        const edgeKey = `${edge.data.source}__${edge.data.target}`;
        if (!existingIds.has(edgeKey)) {
          newElements.push({ data: { ...edge.data, id: edgeKey } });
        }
      }
      if (newElements.length > 0) {
        cy.add(newElements);
        // Apply centrality sizing if returned
        if (data.per_node_centrality) {
          cy.batch(() => {
            for (const [nid, score] of Object.entries(data.per_node_centrality!)) {
              const node = cy.$(`#${nid}`);
              if (node.length > 0) {
                const size = 20 + score * 60; // range 20-80px per CONTEXT.md
                node.style({ width: size, height: size });
              }
            }
          });
        }
        cy.layout({ name: "dagre", rankDir: "TB", nodeSep: 40, rankSep: 60 } as never).run();
      }
    } catch (err) {
      console.error("traverse expand failed", err);
    }
  };

  if (loading) {
    return (
      <div
        data-testid="attack-graph-loading"
        className="animate-pulse bg-muted rounded"
        style={{ height, width: "100%" }}
      />
    );
  }

  if (error) {
    return (
      <div
        data-testid="attack-graph-error"
        style={{
          height,
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "hsl(var(--card))",
          color: "var(--brand-slate)",
          fontSize: 16,
        }}
      >
        Graph unavailable.
      </div>
    );
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div
        data-testid="attack-graph-empty"
        style={{
          height,
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#04342C",
          color: "var(--brand-slate)",
          fontSize: 16,
        }}
      >
        No graph data for this event.
      </div>
    );
  }

  const elements = [
    ...graph.nodes.map((n) => ({ data: n.data })),
    ...graph.edges.map((e) => ({ data: e.data })),
  ];

  return (
    <div
      data-testid="attack-graph-container"
      style={{ width: "100%", background: "#04342C" }}
    >
      <AttackGraphToolbar cy={cyRef.current} />
      <CytoscapeComponent
        elements={elements}
        cy={(instance) => {
          cyRef.current = instance;
          // Register right-click context menu (Phase 28 / GRAPH-02)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (instance as any).contextMenus({
            menuItems: [
              {
                id: "expand-1-hop",
                content: "Expand 1 hop",
                selector: "node",
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                onClickFunction: (event: any) => {
                  handleExpand(event.target.id(), 1);
                },
              },
              {
                id: "expand-3-hops",
                content: "Expand 3 hops",
                selector: "node",
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                onClickFunction: (event: any) => {
                  handleExpand(event.target.id(), 3);
                },
              },
              {
                id: "path-to",
                content: "Path to…",
                selector: "node",
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                onClickFunction: (event: any) => {
                  // Phase 28 stub: log nodeId for future path-finding feature
                  console.info("path-to requested for", event.target.id());
                },
              },
            ],
          });
        }}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        layout={{ name: "dagre", rankDir: "TB", nodeSep: 40, rankSep: 60 } as any}
        style={{ width: "100%", height }}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        stylesheet={NODE_STYLES as any}
      />
    </div>
  );
}
