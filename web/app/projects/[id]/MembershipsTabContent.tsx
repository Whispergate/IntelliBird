"use client";

/**
 * MembershipsTabContent — Memberships tab orchestrator for /projects/[id]
 * (Phase 10 Plan 11, PRJ-05).
 *
 * Owns:
 *   - fetch + refresh cycle for the membership list
 *   - Add-member CTA + dialog
 *   - Empty state ("You are the only member") when the list has no rows
 *   - Delegation to MembershipTable for in-row role change + remove flow
 *
 * Dependencies:
 *   - MembershipTable (this plan) for row layout + last-Lead protection
 *   - MembershipDialog (this plan) for the add-member modal
 *   - listMemberships / addMember from web/app/projects/lib/api.ts (10-08)
 *
 * The component is exported as a plain function (not default) to match the
 * sibling file convention established by OverviewClient in plan 10-09.
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import type {
  MembershipCreateBody,
  MembershipResponse,
  ProjectResponse,
} from "../lib/api";
import { addMember, listMemberships } from "../lib/api";
import { Button } from "@/components/ui/button";
import { MembershipDialog } from "./components/MembershipDialog";
import { MembershipTable } from "./components/MembershipTable";

export function MembershipsTabContent({
  project,
}: {
  project: ProjectResponse;
}) {
  const [members, setMembers] = useState<MembershipResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);

  const reload = useCallback(async () => {
    try {
      const data = await listMemberships(project.id);
      setMembers(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      toast.error(`Could not load memberships. ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [project.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  async function handleAdd(body: MembershipCreateBody) {
    // Let MembershipDialog handle its own error surfacing — it throws on
    // failure so the dialog stays open and the toast copy is close to the
    // user's action.
    await addMember(project.id, body);
    toast.success(
      `Added ${body.user_sub.slice(0, 16)}${body.user_sub.length > 16 ? "…" : ""} as ${body.project_role}.`,
    );
    setDialogOpen(false);
    await reload();
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="brand-heading text-foreground">Memberships</h2>
          <p className="text-sm text-muted-foreground">
            Project-local roles layered on top of the global role (Admin /
            Analyst / Viewer). A user sees this project when they are a member
            OR a global Admin.
          </p>
        </div>
        <Button
          onClick={() => setDialogOpen(true)}
          style={{
            backgroundColor: "var(--brand-signal)",
            color: "var(--brand-ink)",
          }}
        >
          Add Member
        </Button>
      </div>

      {loading ? (
        <div className="text-muted-foreground">Loading memberships…</div>
      ) : members.length === 0 ? (
        <div className="py-12 text-center text-muted-foreground">
          <h3 className="brand-heading mb-2 text-foreground">
            You are the only member
          </h3>
          <p>
            Invite Contributors or Observers so others can see and act on this
            project.
          </p>
        </div>
      ) : (
        <MembershipTable
          projectId={project.id}
          projectName={project.name}
          members={members}
          onChange={reload}
        />
      )}

      <MembershipDialog
        open={dialogOpen}
        onSubmit={handleAdd}
        onClose={() => setDialogOpen(false)}
      />
    </div>
  );
}
