"use client";

/**
 * ActorProfilesSection — Section 3d: Threat Actor Profiles.
 * Phase 18 plan 18-06. UI-SPEC §3d.
 *
 * Auto-populated + manual. Card grid with ActorProfileCard per actor.
 * Counter "{N} of 3 required actors" colours at ≥3.
 * "Add actor" button expands inline form.
 * readOnly: no add/edit/delete actions.
 */

import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ActorProfileCard } from "../ActorProfileCard";
import { RefreshDiffModal } from "../RefreshDiffModal";
import { createActor, type ActorProfile, type TiberReport } from "../../lib/api";

interface ActorProfilesSectionProps {
  projectId: string;
  report: TiberReport;
  cbestMode: boolean;
  readOnly: boolean;
  actors: ActorProfile[];
  onActorsChange: (actors: ActorProfile[]) => void;
  onReportUpdate?: (updated: TiberReport) => void;
}

export function ActorProfilesSection({
  projectId,
  report,
  readOnly,
  actors,
  onActorsChange,
  onReportUpdate,
}: ActorProfilesSectionProps) {
  const [addingActor, setAddingActor] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [refreshModalOpen, setRefreshModalOpen] = useState(false);

  async function onCreateActor() {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const actor = await createActor({
        projectId,
        reportId: report.id,
        body: { name: newName.trim() },
      });
      onActorsChange([...actors, actor]);
      setNewName("");
      setAddingActor(false);
    } catch (e) {
      toast.error(`Could not add actor. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCreating(false);
    }
  }

  function onActorUpdated(updated: ActorProfile) {
    onActorsChange(actors.map((a) => (a.id === updated.id ? updated : a)));
  }

  function onActorDeleted(id: string) {
    onActorsChange(actors.filter((a) => a.id !== id));
  }

  const actorCount = actors.length;
  const meetsGate = actorCount >= 3;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="brand-heading">Threat Actor Profiles</h2>
        <div className="flex items-center gap-2">
          {!readOnly && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRefreshModalOpen(true)}
            >
              <RefreshCw size={14} className="mr-1" />
              Refresh from project data
            </Button>
          )}
          {!readOnly && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAddingActor(true)}
              disabled={addingActor}
            >
              <UserPlus size={14} className="mr-1" />
              Add actor
            </Button>
          )}
        </div>
      </div>

      {/* Counter */}
      <p
        className={[
          "brand-caption mb-4",
          meetsGate ? "text-green-300" : "text-muted-foreground",
        ].join(" ")}
      >
        {actorCount} of 3 required actor{actorCount !== 1 ? "s" : ""}
      </p>

      {/* Inline add actor form */}
      {addingActor && (
        <div className="mb-4 p-4 border border-border rounded-md bg-card space-y-3">
          <p className="text-sm font-medium">New actor profile</p>
          <div className="space-y-1.5">
            <Label htmlFor="new-actor-name">Name</Label>
            <Input
              id="new-actor-name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. APT29"
              onKeyDown={(e) => {
                if (e.key === "Enter") void onCreateActor();
                if (e.key === "Escape") setAddingActor(false);
              }}
              autoFocus
            />
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={onCreateActor}
              disabled={!newName.trim() || creating}
            >
              {creating ? "Adding…" : "Add actor"}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setAddingActor(false);
                setNewName("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* Actor cards */}
      {actors.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No actor profiles yet. Use &ldquo;Refresh from project data&rdquo; or add manually.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 max-w-2xl">
          {actors.map((actor) => (
            <ActorProfileCard
              key={actor.id}
              actor={actor}
              projectId={projectId}
              reportId={report.id}
              readOnly={readOnly}
              onUpdated={onActorUpdated}
              onDeleted={onActorDeleted}
            />
          ))}
        </div>
      )}

      {/* Refresh diff modal — Surface 5 */}
      {!readOnly && (
        <RefreshDiffModal
          open={refreshModalOpen}
          onOpenChange={setRefreshModalOpen}
          projectId={projectId}
          reportId={report.id}
          section="actor_profiles"
          onApplied={(updatedReport) => {
            onReportUpdate?.(updatedReport);
            setRefreshModalOpen(false);
          }}
        />
      )}
    </div>
  );
}
