"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Plus, LayoutGrid, List } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { KanbanBoard, type CaseStatus } from "./KanbanBoard";
import { CaseTableView, type CaseFilters } from "./CaseTableView";
import { createCase, patchCase, listCases, type CaseRow } from "@/app/api-client";

interface CasesClientProps {
  initialCases: CaseRow[];
  projectId: string;
  initialView: "kanban" | "table";
}

export default function CasesClient({ initialCases, projectId, initialView }: CasesClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const view = (searchParams.get("view") === "table" ? "table" : "kanban") as
    | "kanban"
    | "table";

  const [cases, setCases] = useState<CaseRow[]>(initialCases);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  // New case form state
  const [newTitle, setNewTitle] = useState("");
  const [newSeverity, setNewSeverity] = useState<string>("none");
  const [newDescription, setNewDescription] = useState("");

  function switchView(v: "kanban" | "table") {
    const params = new URLSearchParams(searchParams.toString());
    if (v === "kanban") {
      params.delete("view");
    } else {
      params.set("view", "table");
    }
    router.replace(`?${params.toString()}`);
  }

  async function handleStatusChange(caseId: string, newStatus: CaseStatus) {
    // Optimistic update
    setCases(prev =>
      prev.map(c => (c.id === caseId ? { ...c, status: newStatus } : c))
    );
    try {
      await patchCase(projectId, caseId, { status: newStatus });
    } catch (err) {
      toast.error("Failed to update case status");
      // Revert on error - reload from server
      try {
        const data = await listCases(projectId, { limit: 200 });
        setCases(data.items as unknown as CaseRow[]);
      } catch {
        // silent - UI shows stale data
      }
    }
  }

  async function handleCreateCase() {
    if (!newTitle.trim()) return;
    setIsCreating(true);
    try {
      const created = await createCase(projectId, {
        title: newTitle.trim(),
        severity: newSeverity === "none" ? null : newSeverity,
        description: newDescription.trim() || null,
      });
      setCases(prev => [created as unknown as CaseRow, ...prev]);
      setDialogOpen(false);
      setNewTitle("");
      setNewSeverity("none");
      setNewDescription("");
      toast.success("Case created");
    } catch {
      toast.error("Failed to create case");
    } finally {
      setIsCreating(false);
    }
  }

  function handleCardClick(caseId: string) {
    router.push(`/projects/${projectId}/cases/${caseId}`);
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  function handleFilterChange(_filters: CaseFilters) {
    // CaseTableView handles local filtering; could wire server-side here later
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">Cases</h1>
          <span className="text-sm text-muted-foreground">({cases.length})</span>
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex rounded-md border overflow-hidden">
            <Button
              variant={view === "kanban" ? "default" : "ghost"}
              size="sm"
              className="rounded-none"
              onClick={() => switchView("kanban")}
              aria-label="Kanban view"
            >
              <LayoutGrid className="h-4 w-4 mr-1" />
              Kanban
            </Button>
            <Button
              variant={view === "table" ? "default" : "ghost"}
              size="sm"
              className="rounded-none"
              onClick={() => switchView("table")}
              aria-label="Table view"
            >
              <List className="h-4 w-4 mr-1" />
              Table
            </Button>
          </div>

          {/* New Case button - always visible in both views */}
          <Button size="sm" onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            New Case
          </Button>
        </div>
      </div>

      {/* Main content area */}
      {view === "kanban" ? (
        <KanbanBoard
          cases={cases}
          onStatusChange={handleStatusChange}
          onCardClick={handleCardClick}
        />
      ) : (
        <CaseTableView
          cases={cases}
          onFilterChange={handleFilterChange}
          projectId={projectId}
        />
      )}

      {/* New Case Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>New Case</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="case-title">Title *</Label>
              <Input
                id="case-title"
                placeholder="Case title..."
                value={newTitle}
                onChange={e => setNewTitle(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleCreateCase()}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="case-severity">Severity</Label>
              <Select value={newSeverity} onValueChange={setNewSeverity}>
                <SelectTrigger id="case-severity">
                  <SelectValue placeholder="Select severity" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="critical">Critical</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="case-description">Description</Label>
              <Textarea
                id="case-description"
                placeholder="Optional description..."
                value={newDescription}
                onChange={e => setNewDescription(e.target.value)}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateCase} disabled={!newTitle.trim() || isCreating}>
              {isCreating ? "Creating..." : "Create Case"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
