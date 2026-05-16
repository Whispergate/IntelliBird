"use client";

import { useEffect, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import Cytoscape from "cytoscape";
// eslint-disable-next-line @typescript-eslint/no-require-imports
const coseBilkent = require("cytoscape-cose-bilkent");
import { Loader2 } from "lucide-react";

import { getActorGraph, type ActorGraphData } from "@/app/api-client";

// Guard against double registration if ActorSubGraph is mounted more than once.
let coseBilkentRegistered = false;
if (!coseBilkentRegistered) {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (Cytoscape as any).use(coseBilkent);
    coseBilkentRegistered = true;
  } catch {
    // Plugin already registered — ignore.
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ACTOR_SUBGRAPH_STYLES: any[] = [
  // ── Actor hub node ────────────────────────────────────────────
  {
    selector: "node[type='actor']",
    style: {
      "background-color": "#1D9E75",
      "border-color": "#0F6E56",
      "border-width": 2,
      color: "#E1F5EE",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 40,
      height: 40,
    },
  },
  // ── Campaign node ─────────────────────────────────────────────
  {
    selector: "node[type='campaign']",
    style: {
      "background-color": "#EF9F27",
      "border-color": "#B37C1A",
      "border-width": 2,
      color: "#0D1B2A",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 30,
      height: 30,
    },
  },
  // ── Event node ────────────────────────────────────────────────
  {
    selector: "node[type='event']",
    style: {
      "background-color": "#1B263B",
      "border-color": "#1D9E75",
      "border-width": 1,
      color: "#9FE1CB",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 24,
      height: 24,
    },
  },
  // ── Technique node ────────────────────────────────────────────
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
  // ── IOC node ──────────────────────────────────────────────────
  {
    selector: "node[type='ioc']",
    style: {
      "background-color": "hsl(270, 45%, 35%)",
      "border-color": "hsl(270, 45%, 55%)",
      "border-width": 1,
      color: "#E1F5EE",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 18,
      height: 18,
    },
  },
  // ── Edges ─────────────────────────────────────────────────────
  {
    selector: "edge[label='PART_OF']",
    style: {
      "line-color": "#888780",
      "target-arrow-color": "#888780",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "line-style": "solid",
      width: 1,
    },
  },
  {
    selector: "edge[label='USED_BY']",
    style: {
      "line-color": "#0F6E56",
      "target-arrow-color": "#0F6E56",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "line-style": "dashed",
      width: 1,
    },
  },
  {
    selector: "edge[label='SEEN_IN']",
    style: {
      "line-color": "hsl(270, 45%, 55%)",
      "target-arrow-color": "hsl(270, 45%, 55%)",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "line-style": "dotted",
      width: 1,
    },
  },
  // ── Default edge fallback ─────────────────────────────────────
  {
    selector: "edge",
    style: {
      "line-color": "#888780",
      "target-arrow-color": "#888780",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      width: 1,
    },
  },
];

export function ActorSubGraph({ actorId }: { actorId: string }) {
  const [graph, setGraph] = useState<ActorGraphData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getActorGraph(actorId)
      .then((data) => {
        if (!cancelled) setGraph(data);
      })
      .catch(() => {
        if (!cancelled) setGraph({ nodes: [], edges: [] });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [actorId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center" style={{ minHeight: 480 }}>
        <Loader2 className="animate-spin h-6 w-6 text-teal-400" />
      </div>
    );
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full text-muted-foreground text-sm border border-border rounded-lg"
        style={{ minHeight: 480 }}
      >
        No linked campaigns or events yet
      </div>
    );
  }

  const elements = [
    ...graph.nodes,
    ...graph.edges,
  ];

  return (
    <div
      className="border border-border rounded-lg overflow-hidden"
      style={{ minHeight: 480 }}
    >
      <CytoscapeComponent
        elements={elements}
        stylesheet={ACTOR_SUBGRAPH_STYLES}
        layout={{
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          name: "cose-bilkent" as any,
          nodeRepulsion: 4500,
          idealEdgeLength: 100,
        }}
        style={{ width: "100%", height: 480 }}
        cy={(cy) => {
          cy.fit();
        }}
      />
    </div>
  );
}
