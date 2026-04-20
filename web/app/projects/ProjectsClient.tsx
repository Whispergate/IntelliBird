"use client";

/**
 * ProjectsClient — interactive shell for the /projects list.
 *
 * Owns:
 *   - Local projects array (seeded from server-fetched initialProjects)
 *   - "Show archived" toggle (refetch semantics)
 *   - Create/Edit dialog state
 *   - Mutation handlers (create, archive, restore) with sonner toasts
 *   - Row-click navigation to /projects/[id]
 *
 * Pattern mirrors web/app/sources/SourcesClient.tsx: server component page
 * hands initial data, client component owns all mutation state.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

import {
  archiveProject,
  createProject,
  listProjects,
  restoreProject,
  type ProjectCreateBody,
  type ProjectResponse,
} from "./lib/api";
import { LEGACY_PROJECT_ID } from "./lib/constants";
import { ProjectTable } from "./components/ProjectTable";
import { ProjectDialog } from "./components/ProjectDialog";

type DialogState =
  | { open: false }
  | { open: true; mode: "add" }
  | { open: true; mode: "edit"; initial: ProjectResponse };

// Copy locked by UI-SPEC §Copywriting Contract §Informational copy.
const LEAD_TOAST =
  "You are the project Lead. Add Contributors and Observers from the Memberships tab.";

export function ProjectsClient({
  initialProjects,
}: {
  initialProjects: ProjectResponse[];
}) {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectResponse[]>(initialProjects);
  const [showArchived, setShowArchived] = useState(false);
  const [dialog, setDialog] = useState<DialogState>({ open: false });

  async function refresh(includeArchived: boolean) {
    try {
      setProjects(await listProjects({ includeArchived }));
    } catch {
      // Silent — table keeps stale rows; mutation toasts already fired.
    }
  }

  async function handleCreate(body: ProjectCreateBody) {
    try {
      await createProject(body);
      toast.success(LEAD_TOAST);
      setDialog({ open: false });
      await refresh(showArchived);
    } catch (err) {
      const msg =
        err instanceof Error && err.message
          ? err.message
          : "Check the name and engagement type.";
      toast.error(`Could not save project. ${msg}`);
    }
  }

  async function handleArchive(p: ProjectResponse) {
    try {
      await archiveProject(p.id);
      toast.success(`Archived ${p.name}.`);
      await refresh(showArchived);
    } catch {
      toast.error("Could not archive project.");
    }
  }

  async function handleRestore(p: ProjectResponse) {
    try {
      await restoreProject(p.id);
      toast.success(`Restored ${p.name}.`);
      await refresh(showArchived);
    } catch {
      toast.error("Could not restore project.");
    }
  }

  function handleRowClick(p: ProjectResponse) {
    // Legacy sentinel is non-clickable per UI-SPEC — defence-in-depth, since
    // ProjectTable already elides onClick for that row.
    if (p.id === LEGACY_PROJECT_ID) return;
    router.push(`/projects/${p.id}`);
  }

  function openEdit(p: ProjectResponse) {
    setDialog({ open: true, mode: "edit", initial: p });
  }

  return (
    <div>
      <div
        style={{ marginBottom: "2rem" }}
        className="flex items-center justify-between"
      >
        <div>
          <h1 className="brand-display text-foreground">Projects</h1>
          <p className="text-[16px] leading-[1.7] text-muted-foreground mt-1">
            Scope intel, bind sources, and separate engagements.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={showArchived}
              onCheckedChange={async (v) => {
                setShowArchived(v);
                await refresh(v);
              }}
              aria-label="Show archived projects"
            />
            Show archived
          </label>
          <Button
            onClick={() => setDialog({ open: true, mode: "add" })}
            style={{
              backgroundColor: "var(--brand-signal)",
              color: "var(--brand-ink)",
            }}
            className="font-medium hover:opacity-90"
          >
            New Project
          </Button>
        </div>
      </div>

      <ProjectTable
        projects={projects}
        onRowClick={handleRowClick}
        onEdit={openEdit}
        onArchive={handleArchive}
        onRestore={handleRestore}
      />

      <ProjectDialog
        open={dialog.open}
        mode={dialog.open ? dialog.mode : "add"}
        initial={
          dialog.open && dialog.mode === "edit" ? dialog.initial : undefined
        }
        onSubmit={handleCreate}
        onClose={() => setDialog({ open: false })}
      />
    </div>
  );
}
