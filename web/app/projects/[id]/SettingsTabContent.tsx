"use client";

/**
 * SettingsTabContent — Phase 10 Plan 10-10 (UI-SPEC §/projects/[id] §Settings).
 *
 * Editable settings surface:
 *   - Name            (required; 1..200 chars)
 *   - Engagement type (5-option Select; drives TIBER banner visibility)
 *   - Description     (optional; <=2000 chars)
 *   - Archive toggle  (Archive Project ↔ Restore button)
 *
 * Read-only footer:
 *   - TIBER banner (conditional on engagement_type === 'tiber') — signal-amber
 *     left-border strip per UI-SPEC §Color §Semantic surfaces
 *   - EASMGatePreview — 3 Phase-11 gate fields with "Phase 11 wires this form
 *     live" caption
 *   - Hard-delete informational copy (archive is the only deletion path)
 *
 * Auth gating is NOT enforced client-side here (UI affordances visible, backend
 * rejects unauthorised writes with 403 → error toast). RoleProvider-driven
 * hiding is a plan 10-11/10-14 concern; for 10-10 the server is the gate.
 *
 * Archive confirmation uses native window.confirm (v1.5 precedent) per
 * UI-SPEC §Destructive confirmations — matches /sources delete pattern.
 */

import { useState } from "react";
import { toast } from "sonner";

import type { EngagementType, ProjectResponse } from "../lib/api";
import { archiveProject, restoreProject, updateProject } from "../lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EASMGatePreview } from "./components/EASMGatePreview";

const ENGAGEMENT_OPTIONS: ReadonlyArray<{
  value: EngagementType;
  label: string;
}> = [
  { value: "red_team", label: "Red Team" },
  { value: "tiber", label: "TIBER" },
  { value: "bbest", label: "BBEST" },
  { value: "internal", label: "Internal" },
  { value: "intel_only", label: "Intel-only" },
] as const;

export function SettingsTabContent({
  project,
}: {
  project: ProjectResponse;
}) {
  const [name, setName] = useState(project.name);
  const [engagementType, setEngagementType] = useState<EngagementType>(
    project.engagement_type,
  );
  const [description, setDescription] = useState(project.description ?? "");
  const [archived, setArchived] = useState(project.archived);
  const [saving, setSaving] = useState(false);
  const [archiving, setArchiving] = useState(false);

  const isTiber = engagementType === "tiber";
  const dirty =
    name !== project.name ||
    engagementType !== project.engagement_type ||
    description !== (project.description ?? "");

  async function handleSave() {
    if (!name.trim()) {
      toast.error("Could not save project. Name is required.");
      return;
    }
    setSaving(true);
    try {
      await updateProject(project.id, {
        name: name.trim(),
        engagement_type: engagementType,
        // Send null when the textarea is empty so the backend clears the
        // column rather than storing an empty string.
        description: description.trim() ? description : null,
      });
      toast.success("Project saved.");
    } catch (err) {
      const msg =
        err instanceof Error && err.message
          ? err.message
          : "Check the name and engagement type.";
      toast.error(`Could not save project. ${msg}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleArchiveToggle() {
    if (archiving) return;
    setArchiving(true);
    try {
      if (archived) {
        // Restore — no confirmation step (restore is non-destructive).
        await restoreProject(project.id);
        toast.success(`Restored ${project.name}.`);
        setArchived(false);
      } else {
        // Archive — UI-SPEC §Destructive confirmations body copy.
        const confirmed = window.confirm(
          `Archive this project?\n\n${project.name} will be hidden from the default list. Events, scope, sources, and memberships are retained. You can restore anytime.`,
        );
        if (!confirmed) return;
        await archiveProject(project.id);
        toast.success(`Archived ${project.name}.`);
        setArchived(true);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not change archive state. ${msg}`);
    } finally {
      setArchiving(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <section className="space-y-4">
        <h2 className="brand-heading text-foreground">Project settings</h2>

        <div>
          <Label htmlFor="settings-name">Name</Label>
          <Input
            id="settings-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
          />
        </div>

        <div>
          <Label htmlFor="settings-engagement">Engagement type</Label>
          <Select
            value={engagementType}
            onValueChange={(v) => setEngagementType(v as EngagementType)}
          >
            <SelectTrigger id="settings-engagement">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ENGAGEMENT_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label htmlFor="settings-description">Description</Label>
          <textarea
            id="settings-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={5}
            maxLength={2000}
            className="w-full rounded-md border border-input bg-transparent p-2 text-sm"
          />
        </div>

        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={saving || !dirty}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
          <Button
            variant="outline"
            onClick={handleArchiveToggle}
            disabled={archiving}
          >
            {archived
              ? archiving
                ? "Restoring…"
                : "Restore"
              : archiving
                ? "Archiving…"
                : "Archive Project"}
          </Button>
        </div>
      </section>

      {isTiber && (
        <div
          className="rounded-md bg-card p-4"
          style={{
            borderLeft: "4px solid var(--brand-signal)",
          }}
        >
          <p className="text-foreground">
            <strong>TIBER engagement</strong> — scope-acknowledgement gate
            (Phase 11) governs active scans.
          </p>
        </div>
      )}

      <EASMGatePreview project={project} />

      <section className="border-t border-border pt-4 text-sm text-muted-foreground">
        <p>
          Hard delete is disabled. Archive is the only path — events, scope,
          sources, and memberships remain visible under the Archived toggle on
          /projects.
        </p>
      </section>
    </div>
  );
}
