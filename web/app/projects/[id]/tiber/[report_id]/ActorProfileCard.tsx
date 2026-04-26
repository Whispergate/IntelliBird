"use client";

/**
 * ActorProfileCard — individual actor profile card with inline editing.
 * Phase 18 plan 18-06. UI-SPEC §3d.
 *
 * View mode: displays name / motivation / capability / relevance.
 * Edit mode: inline form on Pencil click; auto-save on blur or explicit Save.
 * readOnly: no edit button, no save button.
 */

import { useState } from "react";
import { toast } from "sonner";
import { Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { deleteActor, patchActor, type ActorProfile } from "../lib/api";

interface ActorProfileCardProps {
  actor: ActorProfile;
  projectId: string;
  reportId: string;
  readOnly: boolean;
  onUpdated: (updated: ActorProfile) => void;
  onDeleted: (id: string) => void;
}

export function ActorProfileCard({
  actor,
  projectId,
  reportId,
  readOnly,
  onUpdated,
  onDeleted,
}: ActorProfileCardProps) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(actor.name);
  const [motivation, setMotivation] = useState(actor.motivation ?? "");
  const [capability, setCapability] = useState(actor.capability_assessment ?? "");
  const [relevance, setRelevance] = useState(actor.relevance_to_target ?? "");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function onSave() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const updated = await patchActor({
        projectId,
        reportId,
        actorId: actor.id,
        body: {
          name: name.trim(),
          motivation: motivation || null,
          capability_assessment: capability || null,
          relevance_to_target: relevance || null,
        },
      });
      onUpdated(updated);
      setEditing(false);
      toast.success("Actor profile saved.");
    } catch (e) {
      toast.error(`Could not save actor. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    setDeleting(true);
    try {
      await deleteActor({ projectId, reportId, actorId: actor.id });
      onDeleted(actor.id);
    } catch (e) {
      toast.error(`Could not delete actor. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDeleting(false);
    }
  }

  if (editing) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">Edit actor profile</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(false)}
                disabled={saving}
              >
                Cancel
              </Button>
              <Button size="sm" onClick={onSave} disabled={saving || !name.trim()}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label className="brand-caption text-muted-foreground">NAME</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. APT29"
            />
          </div>
          <div className="space-y-1">
            <Label className="brand-caption text-muted-foreground">MOTIVATION</Label>
            <Textarea
              rows={2}
              value={motivation}
              onChange={(e) => setMotivation(e.target.value)}
              placeholder="e.g. Espionage, financial gain"
            />
          </div>
          <div className="space-y-1">
            <Label className="brand-caption text-muted-foreground">CAPABILITY</Label>
            <Textarea
              rows={2}
              value={capability}
              onChange={(e) => setCapability(e.target.value)}
              placeholder="e.g. High — known zero-day exploitation capability"
            />
          </div>
          <div className="space-y-1">
            <Label className="brand-caption text-muted-foreground">RELEVANCE</Label>
            <Textarea
              rows={2}
              value={relevance}
              onChange={(e) => setRelevance(e.target.value)}
              placeholder="e.g. Targets financial sector infrastructure in EU"
            />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">{actor.name}</CardTitle>
          {!readOnly && (
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                aria-label="Edit actor profile"
                onClick={() => setEditing(true)}
              >
                <Pencil size={14} />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label="Delete actor profile"
                onClick={onDelete}
                disabled={deleting}
                className="text-destructive hover:text-destructive"
              >
                <Trash2 size={14} />
              </Button>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="text-sm space-y-2">
        <div>
          <span className="text-muted-foreground brand-caption block mb-0.5">MOTIVATION</span>
          <p>{actor.motivation || <span className="text-muted-foreground italic">Not set</span>}</p>
        </div>
        <div>
          <span className="text-muted-foreground brand-caption block mb-0.5">CAPABILITY</span>
          <p>
            {actor.capability_assessment || (
              <span className="text-muted-foreground italic">Not set</span>
            )}
          </p>
        </div>
        <div>
          <span className="text-muted-foreground brand-caption block mb-0.5">RELEVANCE</span>
          <p>
            {actor.relevance_to_target || (
              <span className="text-muted-foreground italic">Not set</span>
            )}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
