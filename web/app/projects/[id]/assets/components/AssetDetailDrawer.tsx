"use client";

/**
 * AssetDetailDrawer — Phase 12.1 plan 12.1-05b (UI-SPEC §Surface 6).
 *
 * Right-side shadcn Sheet drawer. Mounts when `assetId` is non-null.
 *
 * Sections (top-to-bottom):
 *   1. SheetHeader — canonical_target (mono) + Copy button
 *   2. Metadata row — type / scope / stale / First-Last-seen / Scans
 *   3. Findings — newest scan first; per-finding <Collapsible> for Raw BBOT JSON
 *   4. Promoted events — conditional; signal-amber left-border provenance pill
 *   5. Note — <Textarea> with debounced autosave via useNoteAutosave hook
 *
 * Signal-amber (`var(--brand-signal)`) is reserved in this phase to the
 * Promoted events provenance pill only — the table stale badge uses muted
 * grey per UI-SPEC §Color.
 */

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Copy } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { useNoteAutosave } from "../hooks/useNoteAutosave";
import type { AssetScope } from "./AssetsTable";

// ---------------------------------------------------------------------------
// Types — mirror backend GET /api/projects/{id}/assets/{asset_id} schema
// (12.1-02). Generated api-client lands in 12.1-06.
// ---------------------------------------------------------------------------

export interface AssetFinding {
  finding_id: string;
  module: string;
  scan_id: string;
  scan_started_at: string; // ISO
  lifecycle_status: string;
  raw_bbot: unknown;
}

export interface PromotedEventLink {
  event_id: string;
  title: string | null;
  canonical_target: string | null;
  stix_type: string | null;
  observed_at: string; // ISO
}

export interface AssetDetail {
  asset_id: string;
  bbot_event_type: string;
  canonical_target: string;
  scope: AssetScope;
  stale: boolean;
  first_seen: string;
  last_seen: string;
  scan_count: number;
  findings: AssetFinding[];
  promoted_events: PromotedEventLink[];
  note: string;
  note_updated_by: string | null;
  note_updated_at: string | null;
}

export interface AssetDetailDrawerProps {
  projectId: string;
  assetId: string | null;
  onClose: () => void;
  canEditNote: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DATE_FMT = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

const DATETIME_FMT = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  hour12: false,
});

function formatDate(iso: string | null): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "\u2014";
  return DATE_FMT.format(d);
}

function formatDateTimeUtc(iso: string | null): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "\u2014";
  return `${DATETIME_FMT.format(d)} UTC`;
}

function relativeTime(from: Date | null): string {
  if (!from) return "";
  const secs = Math.max(0, Math.floor((Date.now() - from.getTime()) / 1000));
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Scope chip — duplicated here to avoid cross-importing from the table file
// (keeps AssetsTable.tsx as a pure presentation surface; tiny redundancy).
// ---------------------------------------------------------------------------

function ScopeChip({ scope }: { scope: AssetScope }) {
  if (scope === "in_scope") {
    return (
      <Badge
        className="bg-teal-900/40 text-teal-300 hover:bg-teal-900/40"
        title="Target matches at least one active scope row."
      >
        in scope
      </Badge>
    );
  }
  if (scope === "out_of_scope") {
    return (
      <Badge
        className="border border-destructive text-destructive bg-transparent"
        title="Target is outside all active scope rows for this project."
      >
        out of scope
      </Badge>
    );
  }
  return (
    <Badge
      className="bg-muted text-muted-foreground hover:bg-muted"
      title="Target cannot be matched to any scope row (e.g. technology or email without a resolvable host)."
    >
      unscoped
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Finding row — collapsible raw JSON
// ---------------------------------------------------------------------------

function FindingRow({ finding }: { finding: AssetFinding }) {
  const [open, setOpen] = useState(false);
  let rawJson: string;
  try {
    rawJson = JSON.stringify(finding.raw_bbot, null, 2);
  } catch {
    rawJson = "[unserialisable]";
  }
  const scanShort = finding.scan_id.slice(0, 8);
  return (
    <div className="py-3 border-b border-border last:border-0">
      <div className="flex items-baseline gap-3">
        <span className="text-[16px] font-medium">{finding.module}</span>
        <span className="text-[12px] font-mono text-muted-foreground">
          {scanShort}
        </span>
      </div>
      <div className="text-[12px] text-muted-foreground mt-1">
        Scan started: {formatDateTimeUtc(finding.scan_started_at)}
        {" \u00b7 "}
        Lifecycle: {finding.lifecycle_status}
      </div>
      <Collapsible open={open} onOpenChange={setOpen} className="mt-2">
        <CollapsibleTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-[12px]"
          >
            {open ? (
              <ChevronDown className="h-3 w-3 mr-1" />
            ) : (
              <ChevronRight className="h-3 w-3 mr-1" />
            )}
            Raw BBOT JSON
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="bg-muted p-3 rounded-sm whitespace-pre-wrap max-h-96 overflow-y-auto mt-2">
            <code className="text-[12px] font-mono text-muted-foreground">
              {rawJson}
            </code>
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Note editor
// ---------------------------------------------------------------------------

function NoteEditor({
  projectId,
  assetId,
  initialNote,
  canEditNote,
}: {
  projectId: string;
  assetId: string;
  initialNote: string;
  canEditNote: boolean;
}) {
  const disabled = !canEditNote;
  const { draft, setDraft, status, savedAt, retry } = useNoteAutosave({
    projectId,
    assetId,
    initialNote,
    disabled,
  });

  // Tick relative-time label every 60s while "saved".
  const [, setTick] = useState(0);
  useEffect(() => {
    if (status !== "saved") return;
    const t = setInterval(() => setTick((n) => n + 1), 60_000);
    return () => clearInterval(t);
  }, [status]);

  const textarea = (
    <Textarea
      rows={4}
      value={draft}
      disabled={disabled}
      placeholder="Add a note for this asset — ownership, context, follow-up…"
      onChange={(e) => setDraft(e.target.value)}
      data-testid="asset-note-textarea"
    />
  );

  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-[22px] font-medium">Note</h3>
      <p className="text-[12px] text-muted-foreground">
        Free-text note on this asset, visible to all project members.
      </p>
      {disabled ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-block">{textarea}</span>
            </TooltipTrigger>
            <TooltipContent>
              You do not have permission to edit notes on this project.
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        textarea
      )}
      <div
        className="text-[12px] text-muted-foreground min-h-4"
        data-testid="asset-note-status"
      >
        {status === "typing" && <span>Typing…</span>}
        {status === "saving" && <span>Saving…</span>}
        {status === "saved" && (
          <span>Saved {relativeTime(savedAt)}</span>
        )}
        {status === "error" && (
          <span className="flex items-center gap-2">
            <span className="text-destructive">Could not save note. Retry.</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={retry}
              className="h-6 px-2 text-[12px]"
            >
              Retry
            </Button>
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AssetDetailDrawer
// ---------------------------------------------------------------------------

export function AssetDetailDrawer({
  projectId,
  assetId,
  onClose,
  canEditNote,
}: AssetDetailDrawerProps) {
  const open = assetId !== null;
  const [detail, setDetail] = useState<AssetDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!assetId) {
      setDetail(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/api/projects/${projectId}/assets/${assetId}`, {
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`detail ${res.status}`);
        const json = (await res.json()) as AssetDetail;
        if (!cancelled) setDetail(json);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load asset details.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, assetId]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) onClose();
  };

  async function onCopyTarget() {
    if (!detail) return;
    try {
      await navigator.clipboard.writeText(detail.canonical_target);
      toast("Target copied to clipboard.");
    } catch {
      toast("Target copied to clipboard.");
    }
  }

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-2xl overflow-y-auto"
      >
        {loading && (
          <div className="flex flex-col gap-4 py-8">
            <div className="animate-pulse bg-muted/40 h-6 w-2/3 rounded" />
            <div className="animate-pulse bg-muted/40 h-4 w-1/2 rounded" />
          </div>
        )}

        {error && !loading && (
          <div className="flex flex-col gap-3 py-8">
            <p className="text-[16px]">{error}</p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                // Re-fetch by toggling assetId dep: nudge via a dummy state update isn't
                // available here; ask parent to close + user re-opens. Keep simple for v1.
                if (assetId) {
                  // Re-run effect by forcing a state reset.
                  setError(null);
                  setLoading(true);
                  fetch(`/api/projects/${projectId}/assets/${assetId}`, {
                    credentials: "include",
                  })
                    .then(async (r) => {
                      if (!r.ok) throw new Error("retry");
                      const j = (await r.json()) as AssetDetail;
                      setDetail(j);
                    })
                    .catch(() => setError("Could not load asset details."))
                    .finally(() => setLoading(false));
                }
              }}
            >
              Retry
            </Button>
          </div>
        )}

        {detail && !loading && !error && (
          <>
            <SheetHeader>
              <div className="flex items-center gap-2">
                <SheetTitle className="font-mono text-[22px] truncate">
                  {detail.canonical_target}
                </SheetTitle>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label="Copy target to clipboard"
                        onClick={onCopyTarget}
                        className="h-6 w-6"
                      >
                        <Copy className="h-3 w-3" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Copy target</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
                <Badge className="bg-muted text-muted-foreground hover:bg-muted font-medium text-[12px]">
                  {detail.bbot_event_type}
                </Badge>
                <ScopeChip scope={detail.scope} />
                {detail.stale && (
                  <Badge
                    className="bg-muted text-muted-foreground hover:bg-muted font-medium text-[12px]"
                    title="Not seen in the most recent completed scan."
                  >
                    Stale
                  </Badge>
                )}
                <span>First seen: {formatDate(detail.first_seen)}</span>
                <span>Last seen: {formatDate(detail.last_seen)}</span>
                <span>Scans: {detail.scan_count}</span>
              </div>
            </SheetHeader>

            <div className="mt-6 flex flex-col gap-6">
              {/* Findings */}
              <section>
                <div className="flex items-baseline gap-2">
                  <h3 className="text-[22px] font-medium">Findings</h3>
                  <span className="text-[12px] text-muted-foreground">
                    {detail.findings.length}
                  </span>
                </div>
                {detail.findings.length === 0 ? (
                  <p className="text-[12px] text-muted-foreground mt-2">
                    No finding rows for this asset.
                  </p>
                ) : (
                  <div className="mt-2">
                    {detail.findings.map((f) => (
                      <FindingRow key={f.finding_id} finding={f} />
                    ))}
                  </div>
                )}
              </section>

              {/* Promoted events — conditional */}
              {detail.promoted_events.length > 0 && (
                <section>
                  <div className="flex items-baseline gap-2">
                    <h3 className="text-[22px] font-medium">Promoted events</h3>
                    <span className="text-[12px] text-muted-foreground">
                      {detail.promoted_events.length}
                    </span>
                  </div>
                  <p className="text-[12px] text-muted-foreground mt-1">
                    Events promoted from this asset&apos;s findings via the EASM allowlist.
                  </p>
                  <div className="mt-2 flex flex-col gap-2">
                    {detail.promoted_events.map((evt) => (
                      <div
                        key={evt.event_id}
                        className="flex flex-col gap-1 py-2 border-b border-border last:border-0"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-[16px]">
                            {evt.title ?? evt.canonical_target ?? "(untitled)"}
                          </span>
                          <span
                            className="inline-flex items-center h-4 px-2 border-l-2 border-[var(--brand-signal)] text-[12px] font-mono font-medium uppercase tracking-[0.15em] text-muted-foreground rounded-sm"
                            title="Event promoted from BBOT finding"
                          >
                            BBOT
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                          {evt.stix_type && (
                            <Badge className="bg-muted text-muted-foreground hover:bg-muted text-[12px]">
                              {evt.stix_type}
                            </Badge>
                          )}
                          <span>{formatDateTimeUtc(evt.observed_at)}</span>
                          <a
                            href={`/events?event_id=${encodeURIComponent(evt.event_id)}`}
                            className="text-[12px] underline ml-auto"
                          >
                            View in events →
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Note */}
              <section>
                <NoteEditor
                  projectId={projectId}
                  assetId={detail.asset_id}
                  initialNote={detail.note ?? ""}
                  canEditNote={canEditNote}
                />
                {detail.note_updated_by && detail.note_updated_at && (
                  <div className="text-[12px] text-muted-foreground mt-2">
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span>
                            Last edited by{" "}
                            {detail.note_updated_by.slice(0, 20)}… on{" "}
                            {formatDateTimeUtc(detail.note_updated_at)}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>{detail.note_updated_by}</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                )}
              </section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
