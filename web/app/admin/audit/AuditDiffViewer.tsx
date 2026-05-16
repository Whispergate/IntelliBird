"use client";
import React from "react";
import { ScrollArea } from "@/components/ui/scroll-area";

type DiffViewerProps = {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  onCollapse: () => void;
};

function renderDiffJson(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
  side: "before" | "after"
): React.ReactNode {
  const data = side === "before" ? before : after;
  if (!data) return <span className="text-muted-foreground italic">null</span>;

  const beforeKeys = new Set(Object.keys(before ?? {}));
  const afterKeys = new Set(Object.keys(after ?? {}));

  return (
    <div className="font-mono text-[13px] leading-[1.6] whitespace-pre-wrap">
      {"{"}
      {Object.entries(data).map(([key, val]) => {
        let colorClass = "text-muted-foreground";
        if (side === "after" && !beforeKeys.has(key)) colorClass = "text-green-300";
        if (side === "before" && !afterKeys.has(key)) colorClass = "text-red-400";
        return (
          <div key={key} className={colorClass}>
            {"  "}{JSON.stringify(key)}: {JSON.stringify(val)}
          </div>
        );
      })}
      {"}"}
    </div>
  );
}

export function AuditDiffViewer({ before, after, onCollapse }: DiffViewerProps) {
  return (
    <div className="grid grid-cols-2 gap-4 p-4 bg-card/50 rounded-lg border border-border">
      <div>
        <p className="text-[12px] font-medium uppercase tracking-wide text-muted-foreground mb-2">Before</p>
        <ScrollArea className="max-h-[320px] overflow-x-auto">
          {renderDiffJson(before, after, "before")}
        </ScrollArea>
      </div>
      <div>
        <p className="text-[12px] font-medium uppercase tracking-wide text-muted-foreground mb-2">After</p>
        <ScrollArea className="max-h-[320px] overflow-x-auto">
          {renderDiffJson(before, after, "after")}
        </ScrollArea>
      </div>
      <div className="col-span-2 text-right">
        <button
          onClick={onCollapse}
          className="text-[12px] text-muted-foreground hover:text-foreground underline"
        >
          Collapse
        </button>
      </div>
    </div>
  );
}
