"use client";

/**
 * MembershipDialog - Add-member modal for Memberships tab (
 * PRJ-05).
 *
 * UI-SPEC §/projects/[id] detail §Memberships tab locks:
 *   - Authentik user_sub text input (validated as non-empty; server 422 if
 *     unknown)
 *   - project_role RadioGroup with three options (Lead / Contributor /
 *     Observer), default Contributor
 *   - Save CTA in signal amber (per UI-SPEC §Color §Accent reserved-for list
 *     "Add Member" button)
 *
 * Error surfacing:
 *   - Empty user_sub → client-side toast (no round-trip)
 *   - Backend 422 "User not found in Authentik" → toast copy from UI-SPEC
 *   - Backend 409 membership_exists → distinct copy (spec-implied - explicit
 *     about duplicate rather than "user not found")
 *
 * Note on form shape: this dialog mirrors ProjectDialog from plan 10-08 in
 * dialog styling + button placement, but does NOT use react-hook-form +
 * zodResolver here - the two-field shape is trivial enough that local useState
 * is clearer. Upgrading to RHF if the form grows (e.g., assign-to-team, invite
 * expiry) is a v2.1 refactor.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";

import type { MembershipCreateBody } from "../../lib/api";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

type Role = "Lead" | "Contributor" | "Observer";

export function MembershipDialog({
  open,
  onSubmit,
  onClose,
}: {
  open: boolean;
  onSubmit: (body: MembershipCreateBody) => Promise<void>;
  onClose: () => void;
}) {
  const [userSub, setUserSub] = useState("");
  const [role, setRole] = useState<Role>("Contributor");
  const [busy, setBusy] = useState(false);

  // Reset form each time the dialog opens (matches ProjectDialog reset pattern
  // from plan 10-08). Avoids stale-value carry-over on second open.
  useEffect(() => {
    if (open) {
      setUserSub("");
      setRole("Contributor");
      setBusy(false);
    }
  }, [open]);

  async function submit() {
    const trimmed = userSub.trim();
    if (!trimmed) {
      toast.error("User sub is required.");
      return;
    }
    setBusy(true);
    try {
      await onSubmit({ user_sub: trimmed, project_role: role });
      // onSubmit is responsible for closing the dialog on success so the
      // parent can orchestrate reload + toast copy.
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      if (msg.includes("membership_exists")) {
        toast.error("This user is already a member of the project.");
      } else if (msg.includes("legacy_project_immutable")) {
        toast.error("The legacy project is read-only and cannot be modified.");
      } else if (msg.includes("user") || msg.includes("sub")) {
        toast.error("User not found in Authentik. Confirm the sub is correct.");
      } else {
        toast.error(`Could not add member. ${msg}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add member</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="membership-sub">Authentik user sub</Label>
            <Input
              id="membership-sub"
              value={userSub}
              onChange={(e) => setUserSub(e.target.value)}
              placeholder="e.g. 01F8KXWNTH6N..."
              maxLength={400}
              className="brand-mono"
              aria-label="Authentik subject identifier"
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              The <code className="brand-mono">sub</code> claim from the user&apos;s
              Authentik profile. Ask them to check{" "}
              <code className="brand-mono">/if/user/#/settings</code> if unsure.
            </p>
          </div>
          <div className="space-y-2">
            <Label>Project role</Label>
            <RadioGroup
              value={role}
              onValueChange={(v) => setRole(v as Role)}
              className="gap-2"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="Lead" id="role-lead" />
                <Label htmlFor="role-lead" className="font-normal">
                  <span className="font-medium">Lead</span> - project admin
                  (add/remove members, edit settings, bind sources, export)
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="Contributor" id="role-contrib" />
                <Label htmlFor="role-contrib" className="font-normal">
                  <span className="font-medium">Contributor</span> - edit
                  scope and tags (default)
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="Observer" id="role-observer" />
                <Label htmlFor="role-observer" className="font-normal">
                  <span className="font-medium">Observer</span> - read-only
                  access to intel, graph, and scope
                </Label>
              </div>
            </RadioGroup>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={busy}
            style={{
              backgroundColor: "var(--brand-signal)",
              color: "var(--brand-ink)",
            }}
          >
            {busy ? "Adding…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
