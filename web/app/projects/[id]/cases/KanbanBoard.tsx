"use client";

import { DndContext, DragEndEvent, useDroppable } from "@dnd-kit/core";
import { KanbanCard } from "./KanbanCard";

export type CaseStatus = "open" | "in_progress" | "on_hold" | "resolved" | "closed";

export interface CaseRow {
  id: string;
  title: string;
  status: CaseStatus;
  severity: string | null;
  assignee_user_sub: string | null;
}

const STATUS_COLUMNS: { key: CaseStatus; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "in_progress", label: "In Progress" },
  { key: "on_hold", label: "On Hold" },
  { key: "resolved", label: "Resolved" },
  { key: "closed", label: "Closed" },
];

interface KanbanBoardProps {
  cases: CaseRow[];
  onStatusChange: (caseId: string, newStatus: CaseStatus) => void;
  onCardClick: (caseId: string) => void;
}

export function KanbanBoard({ cases, onStatusChange, onCardClick }: KanbanBoardProps) {
  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    // CRITICAL: Only fire PATCH on drop (not during drag hover)
    if (!over) return;
    const newStatus = over.id as CaseStatus;
    const caseId = String(active.id);
    const currentCase = cases.find(c => c.id === caseId);
    if (!currentCase || currentCase.status === newStatus) return;
    onStatusChange(caseId, newStatus);
  }

  const grouped = STATUS_COLUMNS.reduce((acc, col) => {
    acc[col.key] = cases.filter(c => c.status === col.key);
    return acc;
  }, {} as Record<CaseStatus, CaseRow[]>);

  return (
    <DndContext onDragEnd={handleDragEnd}>
      <div className="flex gap-3 overflow-x-auto pb-4">
        {STATUS_COLUMNS.map(col => (
          <KanbanColumn
            key={col.key}
            status={col.key}
            label={col.label}
            cases={grouped[col.key]}
            onCardClick={onCardClick}
          />
        ))}
      </div>
    </DndContext>
  );
}

function KanbanColumn({
  status,
  label,
  cases,
  onCardClick,
}: {
  status: CaseStatus;
  label: string;
  cases: CaseRow[];
  onCardClick: (id: string) => void;
}) {
  const { isOver, setNodeRef } = useDroppable({ id: status });
  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col gap-2 min-w-[220px] rounded-lg p-3 bg-muted/40 border ${
        isOver ? "border-primary" : "border-transparent"
      }`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-semibold text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">{cases.length}</span>
      </div>
      {cases.map(c => (
        <KanbanCard key={c.id} caseRow={c} onCardClick={onCardClick} />
      ))}
    </div>
  );
}
