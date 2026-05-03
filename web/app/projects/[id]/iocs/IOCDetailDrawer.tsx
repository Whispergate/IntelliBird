"use client";

/**
 * IOCDetailDrawer — Phase 22 Plan 06 (UI-SPEC §Surface 4 a/b/c/d/e + §Surface 7).
 *
 * shadcn Sheet (right side, sm:max-w-xl) with:
 *   - 4a Header: Type/Status/Confidence pills + value + normalised
 *   - 4b Metadata grid
 *   - 4c Linked events list
 *   - 4d Actions footer: Whitelist Switch (Lead+) + Edit (Lead+) + Delete (Admin)
 *   - 4e Edit panel (collapsible): confidence + ttl_days → PATCH
 *   - 7   Delete confirm dialog: hard delete via DELETE /api/iocs/{id}
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Pencil, Trash2 } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

import {
  getIOC,
  getIOCEvents,
  whitelistIOC,
  unwhitelistIOC,
  patchIOC,
  deleteIOC,
  type IOCRead,
  type IOCEventSummary,
} from "@/app/api-client";
import { useProjectRole } from "@/app/projects/[id]/ProjectRoleProvider";
import { TypeBadge, StatusPill, ConfidenceBadge, SourceBadge } from "./badges";

interface Props {
  iocId: string;
  projectId: string;
  onClose: () => void;
  onMutate: () => void;
}

function fmtAbs(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
  } catch {
    return iso;
  }
}

export function IOCDetailDrawer({ iocId, projectId, onClose, onMutate }: Props) {
  const { isAdmin, isLead } = useProjectRole();
  const [ioc, setIoc] = useState<IOCRead | null>(null);
  const [events, setEvents] = useState<IOCEventSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editConfidence, setEditConfidence] = useState<string>("");
  const [editTtlDays, setEditTtlDays] = useState<string>("");
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([getIOC(iocId), getIOCEvents(iocId, 10)])
      .then(([row, evts]) => {
        if (cancelled) return;
        setIoc(row);
        setEvents(evts);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        toast.error(`IOC not found. ${msg}`);
        onClose();
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [iocId, onClose]);

  const canEdit =
    !!ioc &&
    ((ioc.project_id === null && isAdmin) ||
      (ioc.project_id !== null && isLead));

  async function handleWhitelistToggle() {
    if (!ioc) return;
    const isWhitelisted = ioc.status === "whitelisted";
    try {
      let updated: IOCRead;
      if (isWhitelisted) {
        updated = await unwhitelistIOC(ioc.id);
        toast.success("IOC unwhitelisted.");
      } else {
        const opts =
          ioc.project_id === null && !isAdmin
            ? { projectId }
            : ioc.project_id !== null
              ? { projectId: ioc.project_id }
              : {};
        updated = await whitelistIOC(ioc.id, opts);
        toast.success("IOC whitelisted.");
      }
      setIoc(updated);
      onMutate();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Could not update IOC. ${msg}`);
    }
  }

  function openEdit() {
    if (!ioc) return;
    setEditConfidence(ioc.confidence);
    setEditTtlDays(String(ioc.ttl_days));
    setEditing(true);
  }

  async function saveEdit() {
    if (!ioc) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {};
      if (editConfidence) body.confidence = editConfidence;
      const ttl = Number(editTtlDays);
      if (isFinite(ttl) && ttl > 0) body.ttl_days = ttl;
      const updated = await patchIOC(ioc.id, body);
      setIoc(updated);
      setEditing(false);
      toast.success("IOC updated.");
      onMutate();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Could not update IOC. ${msg}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!ioc) return;
    try {
      await deleteIOC(ioc.id);
      toast.success("IOC deleted.");
      setConfirmDeleteOpen(false);
      onMutate();
      onClose();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Could not delete IOC. ${msg}`);
    }
  }

  return (
    <>
      <Sheet open onOpenChange={(open) => !open && onClose()}>
        <SheetContent
          side="right"
          className="sm:max-w-xl w-full overflow-y-auto p-0"
        >
          <SheetHeader className="px-6 py-4 border-b border-border">
            <SheetTitle>IOC detail</SheetTitle>
          </SheetHeader>

          {loading || !ioc ? (
            <div className="p-6 space-y-3">
              <div className="h-4 bg-muted animate-pulse rounded" />
              <div className="h-4 bg-muted animate-pulse rounded w-3/4" />
              <div className="h-32 bg-muted animate-pulse rounded" />
            </div>
          ) : (
            <>
              {/* 4a Header */}
              <div className="flex flex-col gap-2 px-6 pb-4 pt-4 border-b border-border">
                <div className="flex items-center gap-2 flex-wrap">
                  <TypeBadge type={ioc.type} />
                  <StatusPill status={ioc.status} />
                  <ConfidenceBadge confidence={ioc.confidence} />
                  {ioc.project_id === null && (
                    <Badge variant="outline">Global</Badge>
                  )}
                </div>
                <p className="font-mono text-[14px] text-foreground break-all">
                  {ioc.value}
                </p>
                {ioc.normalized_value && ioc.normalized_value !== ioc.value && (
                  <p className="font-mono text-[12px] text-muted-foreground break-all">
                    → {ioc.normalized_value}
                  </p>
                )}
              </div>

              {/* 4b Metadata */}
              <div className="px-6 py-4 border-b border-border bg-card/40">
                <h3 className="brand-caption text-muted-foreground uppercase mb-3">
                  Metadata
                </h3>
                <dl className="grid grid-cols-[140px_1fr] gap-y-3 gap-x-4 text-[13px]">
                  <dt className="text-muted-foreground">First seen</dt>
                  <dd className="font-mono">{fmtAbs(ioc.first_seen)}</dd>
                  <dt className="text-muted-foreground">Last seen</dt>
                  <dd className="font-mono">{fmtAbs(ioc.last_seen)}</dd>
                  <dt className="text-muted-foreground">TTL (days)</dt>
                  <dd className="font-mono">
                    {ioc.ttl_days}
                    {ioc.status === "expired" && (
                      <span className="ml-2 text-muted-foreground italic">
                        (expired)
                      </span>
                    )}
                  </dd>
                  <dt className="text-muted-foreground">Source</dt>
                  <dd>
                    <SourceBadge source={ioc.source} />
                  </dd>
                  <dt className="text-muted-foreground">Project</dt>
                  <dd>
                    {ioc.project_id === null ? (
                      <Badge variant="outline">Global</Badge>
                    ) : (
                      <span className="font-mono text-[12px]">
                        {ioc.project_id}
                      </span>
                    )}
                  </dd>
                  <dt className="text-muted-foreground">Created by</dt>
                  <dd className="text-[12px] text-muted-foreground truncate">
                    {ioc.created_by ?? "—"}
                  </dd>
                </dl>
              </div>

              {/* 4c Linked events */}
              <div className="px-6 py-4 border-b border-border">
                <h3 className="brand-caption text-muted-foreground uppercase mb-3">
                  Linked events ({events.length})
                </h3>
                {events.length === 0 ? (
                  <p className="text-[12px] text-muted-foreground py-4">
                    No events linked to this IOC.
                  </p>
                ) : (
                  <ul className="flex flex-col">
                    {events.map((e) => (
                      <li key={e.id}>
                        <div className="w-full flex flex-col gap-1 py-2 px-3 rounded-sm border-b border-border/40 last:border-b-0">
                          <div className="flex items-baseline gap-2">
                            <span className="brand-caption text-muted-foreground font-mono">
                              [{fmtAbs(e.observed_at)}]
                            </span>
                            <span className="brand-caption text-muted-foreground truncate">
                              {e.stix_type ?? ""}
                            </span>
                          </div>
                          <p className="text-sm text-foreground line-clamp-2">
                            {e.title}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* 4e Edit panel */}
              {editing && canEdit && (
                <div className="px-6 py-4 border-b border-border space-y-3 bg-card/40">
                  <h3 className="brand-caption text-muted-foreground uppercase">
                    Edit IOC
                  </h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="flex flex-col gap-1">
                      <Label htmlFor="edit-confidence" className="text-xs">
                        Confidence
                      </Label>
                      <Input
                        id="edit-confidence"
                        type="number"
                        min="0"
                        max="1"
                        step="0.05"
                        value={editConfidence}
                        onChange={(e) => setEditConfidence(e.target.value)}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <Label htmlFor="edit-ttl" className="text-xs">
                        TTL (days)
                      </Label>
                      <Input
                        id="edit-ttl"
                        type="number"
                        min="1"
                        max="3650"
                        step="1"
                        value={editTtlDays}
                        onChange={(e) => setEditTtlDays(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setEditing(false)}
                      disabled={saving}
                    >
                      Cancel
                    </Button>
                    <Button size="sm" onClick={() => void saveEdit()} disabled={saving}>
                      Save
                    </Button>
                  </div>
                </div>
              )}

              {/* 4d Actions footer */}
              <div className="sticky bottom-0 bg-background border-t border-border px-6 py-4 flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                  <Switch
                    id="ioc-whitelist"
                    checked={ioc.status === "whitelisted"}
                    onCheckedChange={() => void handleWhitelistToggle()}
                    disabled={!isLead}
                    aria-label={`Whitelist ${ioc.value}`}
                  />
                  <Label htmlFor="ioc-whitelist" className="text-sm">
                    Whitelisted
                  </Label>
                </div>
                <div className="flex items-center gap-2">
                  {canEdit && !editing && (
                    <Button size="sm" variant="outline" onClick={openEdit}>
                      <Pencil className="size-3.5 mr-1" /> Edit
                    </Button>
                  )}
                  {isAdmin && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="text-destructive border-destructive/40 hover:bg-destructive/10"
                      onClick={() => setConfirmDeleteOpen(true)}
                    >
                      <Trash2 className="size-3.5 mr-1" /> Delete IOC
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* Surface 7 — Delete confirm dialog */}
      <Dialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete IOC?</DialogTitle>
            <DialogDescription>
              Permanently delete this IOC and all its event links?
            </DialogDescription>
          </DialogHeader>
          {ioc && (
            <div className="px-3 py-2 rounded-sm bg-card border border-border">
              <p className="brand-caption text-muted-foreground uppercase mb-1">
                Indicator
              </p>
              <p className="font-mono text-[12px] text-foreground break-all">
                {ioc.value}
              </p>
            </div>
          )}
          <p className="text-[12px] text-muted-foreground leading-[1.7]">
            This action cannot be undone. Whitelisting the IOC instead preserves
            it but excludes it from default views.
          </p>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setConfirmDeleteOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="outline"
              className="text-destructive border-destructive/40 hover:bg-destructive/10"
              onClick={() => void handleDelete()}
            >
              Delete IOC
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
