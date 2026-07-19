"use client";

import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { Badge } from "@/components/ui/badge";
import type { CaseRow } from "./KanbanBoard";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/20 text-red-700 border-red-500/30",
  high: "bg-orange-500/20 text-orange-700 border-orange-500/30",
  medium: "bg-yellow-500/20 text-yellow-700 border-yellow-500/30",
  low: "bg-blue-500/20 text-blue-700 border-blue-500/30",
};

export function KanbanCard({
  caseRow,
  onCardClick,
}: {
  caseRow: CaseRow;
  onCardClick: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: caseRow.id,
  });

  const style = transform
    ? { transform: CSS.Translate.toString(transform) }
    : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`rounded-md border bg-card p-3 shadow-sm cursor-pointer select-none ${
        isDragging ? "opacity-50 shadow-lg" : "hover:shadow-md"
      }`}
      onClick={() => onCardClick(caseRow.id)}
    >
      {/* Drag handle area - separate from click */}
      <div
        className="flex items-start justify-between gap-2 mb-2"
        {...attributes}
        {...listeners}
        onClick={e => e.stopPropagation()} // prevent click-through on drag handle
      >
        <span className="text-sm font-medium leading-snug line-clamp-2">{caseRow.title}</span>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        {caseRow.severity && (
          <Badge
            variant="outline"
            className={`text-xs ${SEVERITY_COLORS[caseRow.severity] ?? ""}`}
          >
            {caseRow.severity}
          </Badge>
        )}
        {caseRow.assignee_user_sub && (
          <span className="text-xs text-muted-foreground truncate max-w-[100px]">
            {caseRow.assignee_user_sub}
          </span>
        )}
      </div>
    </div>
  );
}
