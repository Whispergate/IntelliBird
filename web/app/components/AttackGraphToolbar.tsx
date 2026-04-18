"use client";

import { useState } from "react";
import type Cytoscape from "cytoscape";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";

// ── SessionStorage helpers ──────────────────────────────────────────────────

const LAYOUT_KEY = "intellibird:graph-layout";

function readLayout(): string {
  try {
    return window.sessionStorage.getItem(LAYOUT_KEY) ?? "dagre";
  } catch {
    return "dagre";
  }
}

function writeLayout(name: string): void {
  try {
    window.sessionStorage.setItem(LAYOUT_KEY, name);
  } catch {
    /* ignore */
  }
}

// ── Layout option configs ───────────────────────────────────────────────────

const LAYOUT_CONFIGS: Record<string, Record<string, unknown>> = {
  dagre: { name: "dagre", rankDir: "TB", nodeSep: 40, rankSep: 60 },
  cose: { name: "cose", animate: true, animationDuration: 400 },
  breadthfirst: { name: "breadthfirst", directed: true, padding: 20 },
};

// ── Component ───────────────────────────────────────────────────────────────

type Props = {
  cy: Cytoscape.Core | null;
};

export function AttackGraphToolbar({ cy }: Props) {
  const [layout, setLayout] = useState<string>(() => readLayout());
  const [analystOnly, setAnalystOnly] = useState(false);

  function handleLayoutChange(next: string) {
    setLayout(next);
    writeLayout(next);
    if (cy) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      cy.layout({ ...(LAYOUT_CONFIGS[next] ?? { name: next }) } as any).run();
      cy.fit();
    }
  }

  function handleProvenanceToggle(next: boolean) {
    setAnalystOnly(next);
    if (cy) {
      if (next) {
        cy.elements()
          .not("[tag_source = 'analyst']")
          .style("display", "none");
      } else {
        cy.elements().style("display", "element");
      }
      cy.fit();
    }
  }

  return (
    <div className="h-10 flex items-center gap-2 px-4 bg-card border-b border-border">
      <span className="brand-caption text-muted-foreground mr-1">Layout</span>
      <Select value={layout} onValueChange={handleLayoutChange}>
        <SelectTrigger className="w-[160px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="dagre">Dagre — hierarchy</SelectItem>
          <SelectItem value="cose">CoSE — force</SelectItem>
          <SelectItem value="breadthfirst">Breadth-first</SelectItem>
        </SelectContent>
      </Select>

      <span className="mx-2 text-border">|</span>

      <label className="flex items-center gap-1 cursor-pointer">
        <Switch
          checked={analystOnly}
          onCheckedChange={handleProvenanceToggle}
          aria-label="Show analyst-confirmed nodes only"
        />
        <span style={{ fontSize: 14 }} className="text-foreground">
          Analyst-confirmed only
        </span>
      </label>

      <div className="ml-auto flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          aria-label="Zoom in"
          onClick={() => {
            if (cy) cy.zoom(cy.zoom() * 1.2);
          }}
        >
          <ZoomIn size={16} />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Zoom out"
          onClick={() => {
            if (cy) cy.zoom(cy.zoom() / 1.2);
          }}
        >
          <ZoomOut size={16} />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Fit to content"
          onClick={() => {
            if (cy) cy.fit();
          }}
        >
          <Maximize2 size={16} />
        </Button>
      </div>
    </div>
  );
}
