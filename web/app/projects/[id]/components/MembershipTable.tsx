"use client";

/**
 * MembershipTable - per-project member roster with in-row role dropdown +
 * destructive-confirm remove dialog (PRJ-05).
 *
 * UI-SPEC §/projects/[id] detail §Memberships tab locks:
 *   - columns: user_sub (mono truncated), role badge, added_by (mono), added at, actions
 *   - role change is inline Select → PATCH → toast (no modal)
 *   - remove = shadcn Dialog destructive-confirm
 *   - last-Lead protection: when `leadCount === 1` AND the row being looked at
 *     is the sole Lead, the remove button is disabled with a tooltip-style
 *     `title` reading "Cannot remove the last Lead; promote another member first."
 *     The backend enforces the same invariant (409 cannot_remove_last_lead)
 *     as defence-in-depth; the UI gate is purely a pre-empt.
 *
 * Backend 409 surfacing:
 *   removeMember() throws Error whose `.message` is the FastAPI detail. When
 *   that message contains "cannot_remove_last_lead", the toast copy switches
 *   to the UI-SPEC string. Any other error surface reports the raw detail.
 *
 * Role badge color mapping (inherited from UI-SPEC §Color §Role-color convention):
 *   Lead         → signal amber border trim
 *   Contributor  → mist border trim
 *   Observer     → slate border trim
 */

import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import type { MembershipResponse } from "../../lib/api";
import { removeMember, updateMemberRole } from "../../lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const ROLE_STYLE: Record<string, { border: string; fill: string; color: string }> = {
  Lead: {
    border: "#EF9F27",
    fill: "rgba(239,159,39,0.15)",
    color: "#EF9F27",
  },
  Contributor: {
    border: "#9FE1CB",
    fill: "rgba(159,225,203,0.20)",
    color: "#9FE1CB",
  },
  Observer: {
    border: "#888780",
    fill: "rgba(136,135,128,0.15)",
    color: "#888780",
  },
};

function RoleBadge({ role }: { role: string }) {
  const s = ROLE_STYLE[role] ?? ROLE_STYLE.Observer;
  return (
    <Badge
      className="brand-caption border-transparent"
      style={{
        borderLeft: `4px solid ${s.border}`,
        backgroundColor: s.fill,
        color: s.color,
      }}
    >
      <span className="sr-only">Project role: </span>
      {role}
    </Badge>
  );
}

export function MembershipTable({
  projectId,
  projectName,
  members,
  onChange,
}: {
  projectId: string;
  projectName: string;
  members: MembershipResponse[];
  onChange: () => void;
}) {
  const leadCount = members.filter((m) => m.project_role === "Lead").length;
  const [confirmRemove, setConfirmRemove] = useState<MembershipResponse | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  async function handleRoleChange(
    m: MembershipResponse,
    role: "Lead" | "Contributor" | "Observer",
  ) {
    if (role === m.project_role) return; // Select triggers even on no-change
    try {
      await updateMemberRole(projectId, m.id, role);
      toast.success(`Role updated to ${role}.`);
      onChange();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      if (msg.includes("cannot_remove_last_lead")) {
        toast.error(
          "Cannot remove the last Lead; promote another member first.",
        );
      } else {
        toast.error(`Could not change role. ${msg}`);
      }
      // Re-sync UI from server so the Select shows the actual persisted role
      onChange();
    }
  }

  async function confirmRemoveAndExecute(m: MembershipResponse) {
    setBusy(true);
    try {
      await removeMember(projectId, m.id);
      toast.success("Member removed.");
      setConfirmRemove(null);
      onChange();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      if (msg.includes("cannot_remove_last_lead")) {
        toast.error(
          "Cannot remove the last Lead; promote another member first.",
        );
      } else {
        toast.error(`Could not remove member. ${msg}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-left border-b border-border bg-card">
              <th className="py-2 px-3 brand-caption text-muted-foreground">
                User sub
              </th>
              <th className="py-2 px-3 brand-caption text-muted-foreground">
                Role
              </th>
              <th className="py-2 px-3 brand-caption text-muted-foreground">
                Added by
              </th>
              <th className="py-2 px-3 brand-caption text-muted-foreground">
                Added at
              </th>
              <th className="py-2 px-3 brand-caption text-muted-foreground text-right">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => {
              const isLastLead =
                m.project_role === "Lead" && leadCount === 1;
              return (
                <tr
                  key={m.id}
                  className="border-b border-border/40 last:border-b-0"
                >
                  <td className="py-2 px-3">
                    <span
                      className="brand-mono text-foreground truncate max-w-[24ch] inline-block align-middle"
                      title={m.user_sub}
                      aria-label="Authentik subject identifier"
                    >
                      {m.user_sub}
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-2">
                      <RoleBadge role={m.project_role} />
                      <Select
                        value={m.project_role}
                        onValueChange={(v) =>
                          handleRoleChange(
                            m,
                            v as "Lead" | "Contributor" | "Observer",
                          )
                        }
                      >
                        <SelectTrigger className="h-8 w-[140px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Lead">Lead</SelectItem>
                          <SelectItem value="Contributor">
                            Contributor
                          </SelectItem>
                          <SelectItem value="Observer">Observer</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </td>
                  <td className="py-2 px-3 brand-mono text-muted-foreground">
                    {m.added_by ?? "system"}
                  </td>
                  <td className="py-2 px-3 text-foreground">
                    {m.created_at.slice(0, 10)}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <Button
                      size="icon"
                      variant="ghost"
                      disabled={isLastLead || busy}
                      title={
                        isLastLead
                          ? "Cannot remove the last Lead; promote another member first."
                          : "Remove member"
                      }
                      onClick={() => setConfirmRemove(m)}
                      aria-label={
                        isLastLead
                          ? "Cannot remove the last Lead"
                          : "Remove member"
                      }
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog
        open={!!confirmRemove}
        onOpenChange={(v) => !v && !busy && setConfirmRemove(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Remove {confirmRemove?.user_sub.slice(0, 16)}
              {confirmRemove && confirmRemove.user_sub.length > 16 ? "…" : ""}{" "}
              from {projectName}?
            </DialogTitle>
          </DialogHeader>
          <p className="text-foreground">
            They will lose access to this project&apos;s intel, graph, and
            settings immediately.
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmRemove(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                confirmRemove && confirmRemoveAndExecute(confirmRemove)
              }
              disabled={busy}
            >
              {busy ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
