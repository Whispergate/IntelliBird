"use client";

/**
 * ProjectGraph — -03 (GRAPH-01 frontend), extended -04 (ATK-02..05).
 *
 * Client component that renders a Cytoscape force-layout graph for a project's
 * aggregate threat intelligence. Handles three UI states:
 *
 *   1. Zero events: empty-state card with CTAs to /scope and /sources
 *   2. Events but zero graph edges: "no relationships yet" card with CTA to /events
 *   3. Populated graph: Cytoscape with built-in `cose` layout + truncate banner
 *
 * -04 adds:
 *   - Attack path state machine (infra | loading | attack-path | error)
 *   - "Analyse Attack Path" / "Re-analyse" / "← Back to infrastructure" toolbar
 *   - Pentagon attack-step nodes colored by MITRE tactic
 *   - Truncation banner for windowed analysis responses
 *
 * Layout uses built-in `cose` (NOT cose-bilkent — not installed per RESEARCH §3).
 * NODE_STYLES copied verbatim from AttackGraphImpl.tsx for visual consistency.
 * Background #04342C mirrors the per-event attack graph.
 */

import { useState, useCallback } from "react";
import Link from "next/link";
import CytoscapeComponent from "react-cytoscapejs";
import type Cytoscape from "cytoscape";
import { Button } from "@/components/ui/button";
import type { ProjectGraphResponse } from "@/app/projects/lib/api";
import { analyseAttackPath } from "@/app/projects/lib/api";
import type { AttackPathResponse } from "@/app/projects/lib/api";

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
  // ── DomainPivot node ─────────────────────────────────
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
  // ── Shares-infra edge ─────────────────────────────────
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
  // ── Attack path nodes ─────────────────────────────────────────
  {
    selector: "node[type='attack-step']",
    style: {
      shape: "pentagon",
      "background-color": "#888780",  // tactic sub-selector overrides this
      "border-color": "#E5E7EB",
      "border-width": 2,
      color: "#F8FAFC",
      label: "data(label)",
      "font-size": 10,
      "text-valign": "center",
      "text-halign": "center",
      width: 32,
      height: 32,
    },
  },
  // ── 14 MITRE tactic sub-selector colors ─────────────────────────────────
  { selector: "node[type='attack-step'][tactic='reconnaissance']", style: { "background-color": "#6B21A8" } },
  { selector: "node[type='attack-step'][tactic='resource-development']", style: { "background-color": "#7C3AED" } },
  { selector: "node[type='attack-step'][tactic='initial-access']", style: { "background-color": "#B45309" } },
  { selector: "node[type='attack-step'][tactic='execution']", style: { "background-color": "#D97706" } },
  { selector: "node[type='attack-step'][tactic='persistence']", style: { "background-color": "#1D4ED8" } },
  { selector: "node[type='attack-step'][tactic='privilege-escalation']", style: { "background-color": "#2563EB" } },
  { selector: "node[type='attack-step'][tactic='defense-evasion']", style: { "background-color": "#0891B2" } },
  { selector: "node[type='attack-step'][tactic='credential-access']", style: { "background-color": "#0F766E" } },
  { selector: "node[type='attack-step'][tactic='discovery']", style: { "background-color": "#059669" } },
  { selector: "node[type='attack-step'][tactic='lateral-movement']", style: { "background-color": "#16A34A" } },
  { selector: "node[type='attack-step'][tactic='collection']", style: { "background-color": "#CA8A04" } },
  { selector: "node[type='attack-step'][tactic='command-and-control']", style: { "background-color": "#DC2626" } },
  { selector: "node[type='attack-step'][tactic='exfiltration']", style: { "background-color": "#B91C1C" } },
  { selector: "node[type='attack-step'][tactic='impact']", style: { "background-color": "#7F1D1D" } },
  // ── Attack path edges ────────────────────────────────────────────────────
  {
    selector: "edge[relation='attack-path']",
    style: {
      "line-color": "#E5E7EB",
      "target-arrow-color": "#E5E7EB",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      width: 1.5,
    },
  },
];

// ── Component ───────────────────────────────────────────────────────────────

interface Props {
  data: ProjectGraphResponse;
  projectId: string;
}

export function ProjectGraph({ data, projectId }: Props) {
  const { nodes, edges, truncated } = data;

  // ── Attack path state machine ────────────────────────────────────────────
  type ViewMode = "infra" | "loading" | "attack-path" | "error";
  const [viewMode, setViewMode] = useState<ViewMode>("infra");
  const [attackPathData, setAttackPathData] = useState<AttackPathResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [tooltip, setTooltip] = useState<{ text: string; x: number; y: number } | null>(null);

  const cyCallback = useCallback((cy: Cytoscape.Core) => {
    cy.on("mouseover", "node[type='attack-step']", (evt) => {
      const d = evt.target.data();
      const pos = evt.renderedPosition ?? evt.target.renderedPosition();
      const pct = Math.round((d.confidence ?? 0) * 100);
      setTooltip({ text: `${d.rationale ?? ""} (${pct}% confidence)`, x: pos.x, y: pos.y });
    });
    cy.on("mouseout", "node[type='attack-step']", () => setTooltip(null));
  }, []);

  async function handleAnalyse() {
    setViewMode("loading");
    setErrorMessage("");
    try {
      const result = await analyseAttackPath(projectId);
      setAttackPathData(result);
      setViewMode("attack-path");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("[AttackPath] analysis failed:", err);
      setErrorMessage(msg);
      setViewMode("error");
    }
  }

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

  // State 2: Events present but zero graph relationships — show toolbar + empty-state
  if (nodes.length > 0 && edges.length === 0 && viewMode !== "attack-path") {
    return (
      <div>
        <div className="flex items-center gap-2 px-4 py-2 border-b border-border/40">
          {viewMode === "infra" && (
            <Button
              size="sm"
              onClick={handleAnalyse}
              style={{ backgroundColor: "var(--brand-signal)", color: "var(--brand-ink)" }}
            >
              Analyse Attack Path
            </Button>
          )}
          {viewMode === "loading" && (
            <Button size="sm" disabled style={{ opacity: 0.6 }}>Analysing…</Button>
          )}
          {viewMode === "error" && (
            <>
              <span className="text-destructive text-sm font-medium px-2">{errorMessage}</span>
              <Button size="sm" variant="outline" onClick={() => setViewMode("infra")}>Dismiss</Button>
            </>
          )}
        </div>
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <h2 className="brand-heading text-foreground" style={{ fontSize: 22, fontWeight: 500 }}>
            No graph relationships yet
          </h2>
          <p className="text-muted-foreground max-w-md" style={{ fontSize: 16, lineHeight: 1.7 }}>
            Events haven&apos;t been correlated to actors or techniques yet.
            Use &ldquo;Analyse Attack Path&rdquo; above to let AI reconstruct the kill-chain.
          </p>
          <Link href={`/projects/${projectId}/intel`} aria-label="View events">
            <Button variant="outline">View events</Button>
          </Link>
        </div>
      </div>
    );
  }

  // State 3: Populated graph
  const infraElements = [
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

  const attackPathElements =
    viewMode === "attack-path" && attackPathData
      ? [
          ...attackPathData.nodes.map((n) => ({
            data: {
              id: n.id,
              label: `${n.technique_id}\n${n.name}`,
              type: "attack-step",
              tactic: n.tactic,
              rationale: n.rationale,
              confidence: n.confidence,
            },
          })),
          ...attackPathData.edges.map((e, i) => ({
            data: {
              id: `atk-edge-${i}`,
              source: e.from,
              target: e.to,
              relation: "attack-path",
              rationale: e.rationale,
            },
          })),
        ]
      : [];

  const activeElements = viewMode === "attack-path" ? attackPathElements : infraElements;

  return (
    <div>
      {/* Attack path toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border/40">
        {viewMode === "infra" && (
          <Button
            size="sm"
            onClick={handleAnalyse}
            style={{ backgroundColor: "var(--brand-signal)", color: "var(--brand-ink)" }}
          >
            Analyse Attack Path
          </Button>
        )}
        {viewMode === "loading" && (
          <Button size="sm" disabled style={{ opacity: 0.6 }}>
            Analysing…
          </Button>
        )}
        {viewMode === "attack-path" && (
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setViewMode("infra")}
            >
              ← Back to infrastructure
            </Button>
            <Button
              size="sm"
              onClick={handleAnalyse}
              style={{ backgroundColor: "var(--brand-signal)", color: "var(--brand-ink)" }}
            >
              Re-analyse
            </Button>
          </>
        )}
        {viewMode === "error" && (
          <>
            <span className="text-destructive text-sm font-medium px-2">{errorMessage}</span>
            <Button size="sm" variant="outline" onClick={() => setViewMode("infra")}>Dismiss</Button>
          </>
        )}
      </div>
      {truncated && (
        <div
          data-testid="graph-truncate-banner"
          className="flex items-center gap-2 px-4 py-2 bg-amber-900/30 border-b border-amber-700/40 text-amber-300 text-sm"
        >
          Showing top {nodes.length} nodes (truncated) — narrow scope to refine
        </div>
      )}
      {viewMode === "attack-path" && attackPathData?.truncated && (
        <div
          data-testid="attack-path-truncate-banner"
          className="flex items-center gap-2 px-4 py-2 bg-purple-900/30 border-b border-purple-700/40 text-purple-300 text-sm"
        >
          Analysis based on latest 50 events (window truncated) — narrow date range for full coverage
        </div>
      )}
      <div
        data-testid="project-graph-container"
        style={{ background: "#04342C", height: "calc(100vh - 200px)", position: "relative" }}
      >
        <CytoscapeComponent
          elements={activeElements}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          layout={LAYOUT as any}
          style={{ width: "100%", height: "100%" }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          stylesheet={NODE_STYLES as any}
          cy={cyCallback}
        />
        {tooltip && (
          <div
            data-testid="attack-path-tooltip"
            style={{
              position: "absolute",
              left: tooltip.x + 12,
              top: tooltip.y - 8,
              background: "rgba(15,26,23,0.95)",
              border: "1px solid #374151",
              borderRadius: 6,
              padding: "6px 10px",
              color: "#E1F5EE",
              fontSize: 12,
              maxWidth: 280,
              pointerEvents: "none",
              zIndex: 10,
              lineHeight: 1.5,
            }}
          >
            {tooltip.text}
          </div>
        )}
      </div>
    </div>
  );
}
