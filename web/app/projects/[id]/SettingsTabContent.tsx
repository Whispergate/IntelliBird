"use client";

/**
 * SettingsTabContent - (UI-SPEC §/projects/[id] §Settings).
 *
 * Editable settings surface:
 *   - Name            (required; 1..200 chars)
 *   - Engagement type (5-option Select; drives TIBER banner visibility)
 *   - Description     (optional; <=2000 chars)
 *   - Archive toggle  (Archive Project ↔ Restore button)
 *
 * Read-only footer:
 *   - TIBER banner (conditional on engagement_type === 'tiber') - signal-amber
 *     left-border strip per UI-SPEC §Color §Semantic surfaces
 * - EASMGatePreview - 3 gate fields with " wires this form
 *     live" caption
 *   - Hard-delete informational copy (archive is the only deletion path)
 *
 * Auth gating is NOT enforced client-side here (UI affordances visible, backend
 * rejects unauthorised writes with 403 → error toast). RoleProvider-driven
 * hiding is a plan 10-11/10-14 concern; for 10-10 the server is the gate.
 *
 * Archive confirmation uses native window.confirm (v1.5 precedent) per
 * UI-SPEC §Destructive confirmations - matches /sources delete pattern.
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useSession } from "next-auth/react";

import type { EngagementType, MembershipResponse, ProjectResponse } from "../lib/api";
import {
  archiveProject,
  listMemberships,
  restoreProject,
  updateProject,
  LEGACY_PROJECT_ID,
} from "../lib/api";
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
import { EASMGateForm } from "./components/EASMGateForm";
import type { EASMGateProject } from "./components/EASMGateForm";
import { AIProviderCard } from "./settings/AIProviderCard";
import { EnrichmentProvidersCard } from "./settings/EnrichmentProvidersCard";
import { MispConfigSection } from "./settings/MispConfigSection";

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

type OllamaHealth = "healthy" | "slow" | "down" | "unknown";

export function SettingsTabContent({
  project: initialProject,
  ollamaHealth = "unknown",
}: {
  project: ProjectResponse;
  ollamaHealth?: OllamaHealth;
}) {
  const { data: session } = useSession();
  // Track live project state so gate changes (PATCH/DELETE) refresh the card
  // without a full page reload.
  const [liveProject, setLiveProject] = useState<ProjectResponse>(initialProject);

  const [name, setName] = useState(liveProject.name);
  const [engagementType, setEngagementType] = useState<EngagementType>(
    liveProject.engagement_type,
  );
  const [description, setDescription] = useState(liveProject.description ?? "");
  const [archived, setArchived] = useState(liveProject.archived);
  const [saving, setSaving] = useState(false);
  const [archiving, setArchiving] = useState(false);

  // Authority computation for EASM gate form.
  // Global Admin always has authority; for Lead we check project memberships.
  const [userIsLeadOrAdmin, setUserIsLeadOrAdmin] = useState(false);

  const computeAuthority = useCallback(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const user = (session?.user as any) ?? null;
    // Dev-mode bypass: when AUTH_ENABLED=false there is no Auth.js session and
    // backend AuthMiddleware injects a dev-stub Admin (id="dev-admin"). Mirror
    // that here so UI gates (gate form, scope dialog) match backend authority.
    // NoAuthBanner is the user-visible warning that this is a non-auth deployment.
    if (!user) {
      setUserIsLeadOrAdmin(true);
      return;
    }
    if (user.role === "Admin") {
      setUserIsLeadOrAdmin(true);
      return;
    }
    try {
      const memberships: MembershipResponse[] = await listMemberships(liveProject.id);
      const isLead = memberships.some(
        (m) => m.user_sub === user.sub && m.project_role === "Lead",
      );
      setUserIsLeadOrAdmin(isLead);
    } catch {
      // If memberships fail to load, default to no authority (safe default).
      setUserIsLeadOrAdmin(false);
    }
  }, [session, liveProject.id]);

  useEffect(() => {
    computeAuthority();
  }, [computeAuthority]);

  const isLegacy = liveProject.id === LEGACY_PROJECT_ID;

  const isTiber = engagementType === "tiber";
  const dirty =
    name !== liveProject.name ||
    engagementType !== liveProject.engagement_type ||
    description !== (liveProject.description ?? "");

  async function handleSave() {
    if (!name.trim()) {
      toast.error("Could not save project. Name is required.");
      return;
    }
    setSaving(true);
    try {
      await updateProject(liveProject.id, {
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
        // Restore - no confirmation step (restore is non-destructive).
        await restoreProject(liveProject.id);
        toast.success(`Restored ${liveProject.name}.`);
        setArchived(false);
      } else {
        // Archive - UI-SPEC §Destructive confirmations body copy.
        const confirmed = window.confirm(
          `Archive this project?\n\n${liveProject.name} will be hidden from the default list. Events, scope, sources, and memberships are retained. You can restore anytime.`,
        );
        if (!confirmed) return;
        await archiveProject(liveProject.id);
        toast.success(`Archived ${liveProject.name}.`);
        setArchived(true);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not change archive state. ${msg}`);
    } finally {
      setArchiving(false);
    }
  }

  // Callback for EASMGateForm to update local project state after gate flip/revoke
  function handleGateChanged(updated: EASMGateProject) {
    setLiveProject((prev) => ({
      ...prev,
      active_scans_authorised: updated.active_scans_authorised,
      scope_acknowledgement_text: updated.scope_acknowledgement_text,
      active_auth_confirmed_at: updated.active_auth_confirmed_at,
      active_auth_confirmed_by: updated.active_auth_confirmed_by,
      archived: updated.archived,
    }));
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
            <strong>TIBER engagement</strong> - scope-acknowledgement gate
            governs active scans.
          </p>
        </div>
      )}

      <EASMGateForm
        project={liveProject}
        isLegacy={isLegacy}
        userIsLeadOrAdmin={userIsLeadOrAdmin}
        ttlSeconds={604800}
        onGateChanged={handleGateChanged}
      />

      <section className="border-t border-border pt-4 text-sm text-muted-foreground">
        <p>
          Hard delete is disabled. Archive is the only path - events, scope,
          sources, and memberships remain visible under the Archived toggle on
          /projects.
        </p>
      </section>

      {/* AI Provider card - Lead+ only */}
      {userIsLeadOrAdmin && (
        <AIProviderCard
          projectId={liveProject.id}
          ollamaHealth={ollamaHealth}
        />
      )}

      {/* Enrichment Providers card - Lead+ only for edits, all roles can view */}
      <EnrichmentProvidersCard projectId={liveProject.id} />

      {/* MISP Integration - Lead+ only */}
      <MispConfigSection
        projectId={liveProject.id}
        isLead={userIsLeadOrAdmin}
      />
    </div>
  );
}
