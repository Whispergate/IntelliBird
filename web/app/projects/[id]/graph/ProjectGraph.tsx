"use client";

/**
 * ProjectGraph — Phase 20-03 (GRAPH-01 frontend).
 *
 * Client component that renders a Cytoscape force-layout graph for a project's
 * aggregate threat intelligence. Handles three UI states:
 *
 *   1. Zero events: empty-state card with CTAs to /scope and /sources
 *   2. Events but zero graph edges: "no relationships yet" card with CTA to /events
 *   3. Populated graph: Cytoscape with built-in `cose` layout + truncate banner
 *
 * Layout uses built-in `cose` (NOT cose-bilkent — not installed per RESEARCH §3).
 * NODE_STYLES copied verbatim from AttackGraphImpl.tsx for visual consistency.
 * Background #04342C mirrors the per-event attack graph.
 */

import Link from "next/link";
import CytoscapeComponent from "react-cytoscapejs";
import Cytoscape from "cytoscape";
import { Button } from "@/components/ui/button";
import type { ProjectGraphResponse } from "@/app/projects/lib/api";

// ── Plugin guard ────────────────────────────────────────────────────────────
// cose layout is built-in — no plugin import needed.
// dagre import is intentionally omitted (not needed for project graph).

// ── Layout config — verbatim from AttackGraphToolbar.tsx:39-43 ─────────────
const LAYOUT = { name: "cose", animate: true, animationDuration: 400 };

// ── Styling — verbatim from AttackGraphImpl.tsx NODE_STYLES ────────────────
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
];

// ── Component ───────────────────────────────────────────────────────────────

interface Props {
  data: ProjectGraphResponse;
  projectId: string;
}

export function ProjectGraph({ data, projectId }: Props) {
  const { nodes, edges, truncated } = data;

  // State 1: No events at all
  if (nodes.length === 0 && edges.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
        <h2 className="brand-heading text-foreground" style={{ fontSize: 22, fontWeight: 500 }}>
          No project events yet
        </h2>
        <p className="text-muted-foreground max-w-md" style={{ fontSize: 16, lineHeight: 1.7 }}>
          Add scope or wait for ingest to populate the project attack graph.
        </p>
        <div className="flex gap-3 flex-wrap justify-center">
          <Link href={`/projects/${projectId}/scope`} aria-label="Manage scope">
            <Button
              style={{
                backgroundColor: "var(--brand-signal)",
                color: "var(--brand-ink)",
              }}
            >
              Manage scope
            </Button>
          </Link>
          <Link href="/sources" aria-label="View sources">
            <Button variant="outline">View sources</Button>
          </Link>
        </div>
      </div>
    );
  }

  // State 2: Events present but zero graph relationships
  if (nodes.length > 0 && edges.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
        <h2 className="brand-heading text-foreground" style={{ fontSize: 22, fontWeight: 500 }}>
          No graph relationships yet
        </h2>
        <p className="text-muted-foreground max-w-md" style={{ fontSize: 16, lineHeight: 1.7 }}>
          Events haven&apos;t been correlated to actors or techniques yet.
        </p>
        <Link href={`/projects/${projectId}/intel`} aria-label="View events">
          <Button
            style={{
              backgroundColor: "var(--brand-signal)",
              color: "var(--brand-ink)",
            }}
          >
            View events
          </Button>
        </Link>
      </div>
    );
  }

  // State 3: Populated graph
  const elements = [
    ...nodes.map((n) => ({
      data: {
        id: n.id,
        label: n.label,
        type: n.node_type,
        ...(n.tag_source ? { tag_source: n.tag_source } : {}),
      },
    })),
    ...edges.map((e) => ({
      data: { source: e.source, target: e.target, relation: e.relation },
    })),
  ];

  return (
    <div>
      {truncated && (
        <div
          data-testid="graph-truncate-banner"
          className="flex items-center gap-2 px-4 py-2 bg-amber-900/30 border-b border-amber-700/40 text-amber-300 text-sm"
        >
          Showing top {nodes.length} nodes (truncated) — narrow scope to refine
        </div>
      )}
      <div
        data-testid="project-graph-container"
        style={{ background: "#04342C", height: "calc(100vh - 200px)" }}
      >
        <CytoscapeComponent
          elements={elements}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          layout={LAYOUT as any}
          style={{ width: "100%", height: "100%" }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          stylesheet={NODE_STYLES as any}
        />
      </div>
    </div>
  );
}
