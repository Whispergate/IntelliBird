"use client";

/**
 * CaseDetailClient — Phase 31 Plan 07 (CASE-04, CASE-05).
 *
 * Full-page 4-tab case detail:
 *   Overview  — summary_md as Markdown (pre fallback), AI Summarise polling
 *   Events    — attached events table + attach/detach
 *   IOCs      — attached IOCs table + attach/detach
 *   Activity  — read-only audit_log timeline
 *
 * Poll pattern: POST summarise → GET case every 3s, max 20 polls (60s).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Pencil, Check, X } from "lucide-react";

import {
  getCase,
  getCaseActivity,
  getCaseEvents,
  getCaseIOCs,
  patchCase,
  summariseCase,
  regenerateCaseSummary,
  detachEvent,
  detachIOC,
  attachEvents,
  attachIOCs,
  listCases,
  type CaseRow,
  type CaseActivityEntry,
  type CaseEvidenceEvent,
  type CaseEvidenceIOC,
} from "@/app/api-client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 40;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SEVERITY_COLORS: Record<string, string> = {
  low: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  medium: "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  high: "bg-orange-500/20 text-orange-300 border-orange-500/30",
  critical: "bg-red-500/20 text-red-300 border-red-500/30",
};

function SeverityBadge({ severity }: { severity: string | null }) {
  if (!severity) return <span className="text-muted-foreground text-xs">—</span>;
  const cls = SEVERITY_COLORS[severity] ?? "bg-muted text-muted-foreground";
  return (
    <Badge className={`text-[11px] uppercase font-mono ${cls}`}>
      {severity}
    </Badge>
  );
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Attach Events Dialog
// ---------------------------------------------------------------------------

interface AttachEventsDialogProps {
  projectId: string;
  caseId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

function AttachEventsDialog({
  projectId,
  caseId,
  open,
  onOpenChange,
  onSuccess,
}: AttachEventsDialogProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Array<{ id: string; title: string }>>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [searching, setSearching] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setResults([]);
      setSelected(new Set());
      return;
    }
  }, [open]);

  async function doSearch(q: string) {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/events?q=${encodeURIComponent(q)}&limit=20`);
      if (res.ok) {
        const data = await res.json();
        const items = (data.items ?? data) as Array<{ id: string; title?: string; headline?: string }>;
        setResults(items.map((e) => ({ id: e.id, title: e.title ?? e.headline ?? e.id })));
      }
    } catch {
      // ignore
    } finally {
      setSearching(false);
    }
  }

  function toggleRow(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  async function confirm() {
    if (selected.size === 0) return;
    setSubmitting(true);
    try {
      await attachEvents(projectId, caseId, Array.from(selected));
      toast.success(`Attached ${selected.size} event(s) to case`);
      onSuccess();
      onOpenChange(false);
    } catch (e: unknown) {
      toast.error(`Failed to attach events: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Attach Events</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex gap-2">
            <Input
              placeholder="Search events..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void doSearch(query)}
              className="flex-1"
            />
            <Button size="sm" variant="outline" onClick={() => void doSearch(query)} disabled={searching}>
              {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
            </Button>
          </div>
          {results.length > 0 && (
            <div className="border rounded-md divide-y max-h-60 overflow-y-auto">
              {results.map((r) => (
                <label
                  key={r.id}
                  className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-muted/50"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(r.id)}
                    onChange={() => toggleRow(r.id)}
                    className="h-4 w-4"
                  />
                  <span className="text-sm truncate">{r.title}</span>
                </label>
              ))}
            </div>
          )}
          {results.length === 0 && query && !searching && (
            <p className="text-sm text-muted-foreground">No events found.</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => void confirm()} disabled={selected.size === 0 || submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Attach {selected.size > 0 ? `(${selected.size})` : ""}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Attach IOCs Dialog
// ---------------------------------------------------------------------------

interface AttachIOCsDialogProps {
  projectId: string;
  caseId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

function AttachIOCsDialog({
  projectId,
  caseId,
  open,
  onOpenChange,
  onSuccess,
}: AttachIOCsDialogProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Array<{ id: string; value: string }>>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [searching, setSearching] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setResults([]);
      setSelected(new Set());
    }
  }, [open]);

  async function doSearch(q: string) {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setSearching(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/iocs?q=${encodeURIComponent(q)}&limit=20`);
      if (res.ok) {
        const data = await res.json();
        const items = (Array.isArray(data) ? data : data.items ?? []) as Array<{ id: string; value: string }>;
        setResults(items.map((i) => ({ id: i.id, value: i.value })));
      }
    } catch {
      // ignore
    } finally {
      setSearching(false);
    }
  }

  function toggleRow(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  async function confirm() {
    if (selected.size === 0) return;
    setSubmitting(true);
    try {
      await attachIOCs(projectId, caseId, Array.from(selected));
      toast.success(`Attached ${selected.size} IOC(s) to case`);
      onSuccess();
      onOpenChange(false);
    } catch (e: unknown) {
      toast.error(`Failed to attach IOCs: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Attach IOCs</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex gap-2">
            <Input
              placeholder="Search IOCs..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void doSearch(query)}
              className="flex-1"
            />
            <Button size="sm" variant="outline" onClick={() => void doSearch(query)} disabled={searching}>
              {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
            </Button>
          </div>
          {results.length > 0 && (
            <div className="border rounded-md divide-y max-h-60 overflow-y-auto">
              {results.map((r) => (
                <label
                  key={r.id}
                  className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-muted/50"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(r.id)}
                    onChange={() => toggleRow(r.id)}
                    className="h-4 w-4"
                  />
                  <span className="text-sm font-mono truncate">{r.value}</span>
                </label>
              ))}
            </div>
          )}
          {results.length === 0 && query && !searching && (
            <p className="text-sm text-muted-foreground">No IOCs found.</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => void confirm()} disabled={selected.size === 0 || submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Attach {selected.size > 0 ? `(${selected.size})` : ""}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// CaseDetailClient
// ---------------------------------------------------------------------------

interface Props {
  projectId: string;
  initialCase: CaseRow;
}

export function CaseDetailClient({ projectId, initialCase }: Props) {
  const [caseData, setCaseData] = useState<CaseRow>(initialCase);
  const [isPolling, setIsPolling] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const pollAbortRef = useRef<AbortController | null>(null);

  // Title edit state
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState(initialCase.title);

  // Evidence state
  const [caseEvents, setCaseEvents] = useState<CaseEvidenceEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsOffset, setEventsOffset] = useState(0);
  const [eventsHasMore, setEventsHasMore] = useState(false);
  const [attachEventsOpen, setAttachEventsOpen] = useState(false);

  const [caseIOCs, setCaseIOCs] = useState<CaseEvidenceIOC[]>([]);
  const [iocsLoading, setIocsLoading] = useState(false);
  const [iocsOffset, setIocsOffset] = useState(0);
  const [iocsHasMore, setIocsHasMore] = useState(false);
  const [attachIOCsOpen, setAttachIOCsOpen] = useState(false);

  const [activity, setActivity] = useState<CaseActivityEntry[]>([]);
  const [activityLoading, setActivityLoading] = useState(false);

  const caseId = caseData.id;
  const EVENTS_PAGE = 20;
  const IOCS_PAGE = 20;

  // -------------------------------------------------------------------------
  // Refresh case
  // -------------------------------------------------------------------------

  const refreshCase = useCallback(async () => {
    try {
      const updated = await getCase(projectId, caseId);
      setCaseData(updated);
    } catch {
      // ignore
    }
  }, [projectId, caseId]);

  // -------------------------------------------------------------------------
  // Load evidence tabs
  // -------------------------------------------------------------------------

  const loadEvents = useCallback(async (offset = 0) => {
    setEventsLoading(true);
    try {
      const items = await getCaseEvents(projectId, caseId, { limit: EVENTS_PAGE, offset });
      if (offset === 0) {
        setCaseEvents(items);
      } else {
        setCaseEvents((prev) => [...prev, ...items]);
      }
      setEventsOffset(offset);
      setEventsHasMore(items.length >= EVENTS_PAGE);
    } catch (e: unknown) {
      toast.error(`Failed to load events: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEventsLoading(false);
    }
  }, [projectId, caseId]);

  const loadIOCs = useCallback(async (offset = 0) => {
    setIocsLoading(true);
    try {
      const items = await getCaseIOCs(projectId, caseId, { limit: IOCS_PAGE, offset });
      if (offset === 0) {
        setCaseIOCs(items);
      } else {
        setCaseIOCs((prev) => [...prev, ...items]);
      }
      setIocsOffset(offset);
      setIocsHasMore(items.length >= IOCS_PAGE);
    } catch (e: unknown) {
      toast.error(`Failed to load IOCs: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIocsLoading(false);
    }
  }, [projectId, caseId]);

  const loadActivity = useCallback(async () => {
    setActivityLoading(true);
    try {
      const items = await getCaseActivity(projectId, caseId);
      setActivity(items);
    } catch (e: unknown) {
      toast.error(`Failed to load activity: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setActivityLoading(false);
    }
  }, [projectId, caseId]);

  // Load all tabs on mount
  useEffect(() => {
    void loadEvents(0);
    void loadIOCs(0);
    void loadActivity();
  }, [loadEvents, loadIOCs, loadActivity]);

  // -------------------------------------------------------------------------
  // AI Summarise polling
  // -------------------------------------------------------------------------

  async function pollForSummary(signal: AbortSignal) {
    for (let i = 0; i < MAX_POLLS; i++) {
      if (signal.aborted) return;
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      if (signal.aborted) return;
      try {
        const updated = await getCase(projectId, caseId);
        if (updated.summary_md) {
          setCaseData(updated);
          setIsPolling(false);
          return;
        }
      } catch {
        // retry
      }
    }
    // Timed out
    setIsPolling(false);
    setPollError("Summary generation timed out — try again");
    toast.error("Summary generation timed out — try again");
  }

  function handleSummarise() {
    // Cancel any existing poll
    pollAbortRef.current?.abort();
    const controller = new AbortController();
    pollAbortRef.current = controller;
    setPollError(null);
    setIsPolling(true);

    summariseCase(projectId, caseId)
      .then(() => pollForSummary(controller.signal))
      .catch((e: unknown) => {
        setIsPolling(false);
        toast.error(`Failed to start summarisation: ${e instanceof Error ? e.message : String(e)}`);
      });
  }

  function handleRegenerate() {
    // Cancel any existing poll
    pollAbortRef.current?.abort();
    const controller = new AbortController();
    pollAbortRef.current = controller;
    setPollError(null);
    setIsPolling(true);
    // Optimistically clear summary
    setCaseData((prev) => ({ ...prev, summary_md: null }));

    regenerateCaseSummary(projectId, caseId)
      .then(() => pollForSummary(controller.signal))
      .catch((e: unknown) => {
        setIsPolling(false);
        toast.error(`Failed to regenerate summary: ${e instanceof Error ? e.message : String(e)}`);
      });
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      pollAbortRef.current?.abort();
    };
  }, []);

  // -------------------------------------------------------------------------
  // Title inline edit
  // -------------------------------------------------------------------------

  async function commitTitle() {
    setEditingTitle(false);
    if (titleDraft === caseData.title) return;
    try {
      const updated = await patchCase(projectId, caseId, { title: titleDraft });
      setCaseData(updated);
      toast.success("Title updated");
    } catch (e: unknown) {
      toast.error(`Failed to update title: ${e instanceof Error ? e.message : String(e)}`);
      setTitleDraft(caseData.title);
    }
  }

  function cancelTitleEdit() {
    setEditingTitle(false);
    setTitleDraft(caseData.title);
  }

  // -------------------------------------------------------------------------
  // Status / Assignee changes
  // -------------------------------------------------------------------------

  async function handleStatusChange(status: string) {
    try {
      const updated = await patchCase(projectId, caseId, { status: status as CaseRow["status"] });
      setCaseData(updated);
    } catch (e: unknown) {
      toast.error(`Failed to update status: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // -------------------------------------------------------------------------
  // Event detach
  // -------------------------------------------------------------------------

  async function handleDetachEvent(eventId: string) {
    try {
      await detachEvent(projectId, caseId, eventId);
      setCaseEvents((prev) => prev.filter((e) => e.event_id !== eventId));
      toast.success("Event removed from case");
    } catch (e: unknown) {
      toast.error(`Failed to remove event: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // -------------------------------------------------------------------------
  // IOC detach
  // -------------------------------------------------------------------------

  async function handleDetachIOC(iocId: string) {
    try {
      await detachIOC(projectId, caseId, iocId);
      setCaseIOCs((prev) => prev.filter((i) => i.ioc_id !== iocId));
      toast.success("IOC removed from case");
    } catch (e: unknown) {
      toast.error(`Failed to remove IOC: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="space-y-6 p-4 max-w-5xl mx-auto">
      {/* Page header */}
      <div className="flex items-start gap-4 flex-wrap">
        {/* Title — inline editable */}
        <div className="flex-1 min-w-0">
          {editingTitle ? (
            <div className="flex items-center gap-2">
              <Input
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void commitTitle();
                  if (e.key === "Escape") cancelTitleEdit();
                }}
                autoFocus
                className="text-2xl font-medium h-auto py-1"
              />
              <Button size="icon" variant="ghost" onClick={() => void commitTitle()} aria-label="Save title">
                <Check className="h-4 w-4" />
              </Button>
              <Button size="icon" variant="ghost" onClick={cancelTitleEdit} aria-label="Cancel edit">
                <X className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2 group">
              <h1 className="text-2xl font-medium leading-tight truncate">{caseData.title}</h1>
              <Button
                size="icon"
                variant="ghost"
                className="opacity-0 group-hover:opacity-100 transition-opacity h-7 w-7"
                onClick={() => setEditingTitle(true)}
                aria-label="Edit title"
              >
                <Pencil className="h-3 w-3" />
              </Button>
            </div>
          )}
        </div>

        {/* Severity badge */}
        <SeverityBadge severity={caseData.severity} />

        {/* Status select */}
        <Select value={caseData.status} onValueChange={(v) => void handleStatusChange(v)}>
          <SelectTrigger className="h-8 w-[140px] text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="in_progress">In Progress</SelectItem>
            <SelectItem value="on_hold">On Hold</SelectItem>
            <SelectItem value="resolved">Resolved</SelectItem>
            <SelectItem value="closed">Closed</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview">
        <TabsList className="border-b border-border w-full justify-start rounded-none bg-transparent p-0 h-auto">
          {(["overview", "events", "iocs", "activity"] as const).map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="px-4 py-2 capitalize text-sm rounded-none border-b-2 border-transparent data-[state=active]:border-[var(--brand-signal)] data-[state=active]:bg-transparent data-[state=active]:shadow-none text-muted-foreground data-[state=active]:text-foreground"
            >
              {tab === "iocs" ? "IOCs" : tab.charAt(0).toUpperCase() + tab.slice(1)}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* Overview tab */}
        <TabsContent value="overview" className="space-y-4 pt-4">
          {/* Summary section */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">AI Summary</h2>
              <div className="flex gap-2">
                {caseData.summary_md && !isPolling && (
                  <Button size="sm" variant="outline" onClick={handleRegenerate}>
                    Regenerate
                  </Button>
                )}
                {!caseData.summary_md && !isPolling && (
                  <Button size="sm" onClick={handleSummarise}>
                    AI Summarise
                  </Button>
                )}
                {isPolling && (
                  <Button size="sm" disabled>
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    Generating…
                  </Button>
                )}
              </div>
            </div>

            {pollError && (
              <p className="text-sm text-destructive">{pollError}</p>
            )}

            {caseData.summary_md ? (
              // TODO: npm install react-markdown for rich Markdown rendering
              <pre className="whitespace-pre-wrap text-sm leading-relaxed bg-card/50 rounded-md border border-border p-4 font-sans">
                {caseData.summary_md}
              </pre>
            ) : !isPolling ? (
              <p className="text-sm text-muted-foreground italic">
                No summary yet. Click &quot;AI Summarise&quot; to generate one.
              </p>
            ) : null}
          </div>

          {/* Metadata */}
          <div className="grid grid-cols-2 gap-4 p-4 rounded-md border border-border bg-card/50 text-sm">
            <div>
              <span className="text-muted-foreground">Opened</span>
              <p className="text-foreground">{fmtDate(caseData.opened_at)}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Closed</span>
              <p className="text-foreground">{fmtDate(caseData.closed_at)}</p>
            </div>
            {caseData.assignee_user_sub && (
              <div>
                <span className="text-muted-foreground">Assignee</span>
                <p className="text-foreground font-mono text-xs">{caseData.assignee_user_sub}</p>
              </div>
            )}
            {caseData.description && (
              <div className="col-span-2">
                <span className="text-muted-foreground">Description</span>
                <p className="text-foreground mt-1 whitespace-pre-wrap">{caseData.description}</p>
              </div>
            )}
          </div>
        </TabsContent>

        {/* Events tab */}
        <TabsContent value="events" className="space-y-4 pt-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
              Attached Events
            </h2>
            <Button size="sm" onClick={() => setAttachEventsOpen(true)}>
              Attach Events
            </Button>
          </div>

          {eventsLoading && caseEvents.length === 0 ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : caseEvents.length === 0 ? (
            <p className="text-sm text-muted-foreground italic py-4">No events attached to this case.</p>
          ) : (
            <div className="rounded-md border border-border overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-card/50">
                    <th className="px-3 py-2 text-left text-xs text-muted-foreground font-medium">Event ID</th>
                    <th className="px-3 py-2 text-left text-xs text-muted-foreground font-medium">Attached At</th>
                    <th className="px-3 py-2 text-left text-xs text-muted-foreground font-medium">Attached By</th>
                    <th className="px-3 py-2 w-16" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {caseEvents.map((ev) => (
                    <tr key={ev.event_id} className="hover:bg-muted/30">
                      <td className="px-3 py-2">
                        <a
                          href={`/projects/${projectId}/events?event=${encodeURIComponent(ev.event_id)}`}
                          className="font-mono text-xs text-[var(--brand-signal)] hover:underline"
                        >
                          {ev.event_id.slice(0, 8)}…
                        </a>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{fmtDate(ev.attached_at)}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground font-mono">
                        {ev.attached_by ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-xs text-destructive hover:text-destructive"
                          onClick={() => void handleDetachEvent(ev.event_id)}
                        >
                          Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {eventsHasMore && (
            <div className="flex justify-center">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void loadEvents(eventsOffset + EVENTS_PAGE)}
                disabled={eventsLoading}
              >
                {eventsLoading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                Load more
              </Button>
            </div>
          )}
        </TabsContent>

        {/* IOCs tab */}
        <TabsContent value="iocs" className="space-y-4 pt-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
              Attached IOCs
            </h2>
            <Button size="sm" onClick={() => setAttachIOCsOpen(true)}>
              Attach IOCs
            </Button>
          </div>

          {iocsLoading && caseIOCs.length === 0 ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : caseIOCs.length === 0 ? (
            <p className="text-sm text-muted-foreground italic py-4">No IOCs attached to this case.</p>
          ) : (
            <div className="rounded-md border border-border overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-card/50">
                    <th className="px-3 py-2 text-left text-xs text-muted-foreground font-medium">IOC ID</th>
                    <th className="px-3 py-2 text-left text-xs text-muted-foreground font-medium">Attached At</th>
                    <th className="px-3 py-2 text-left text-xs text-muted-foreground font-medium">Attached By</th>
                    <th className="px-3 py-2 w-16" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {caseIOCs.map((ioc) => (
                    <tr key={ioc.ioc_id} className="hover:bg-muted/30">
                      <td className="px-3 py-2">
                        <a
                          href={`/projects/${projectId}/iocs?ioc=${encodeURIComponent(ioc.ioc_id)}`}
                          className="font-mono text-xs text-[var(--brand-signal)] hover:underline"
                        >
                          {ioc.ioc_id.slice(0, 8)}…
                        </a>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{fmtDate(ioc.attached_at)}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground font-mono">
                        {ioc.attached_by ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-xs text-destructive hover:text-destructive"
                          onClick={() => void handleDetachIOC(ioc.ioc_id)}
                        >
                          Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {iocsHasMore && (
            <div className="flex justify-center">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void loadIOCs(iocsOffset + IOCS_PAGE)}
                disabled={iocsLoading}
              >
                {iocsLoading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                Load more
              </Button>
            </div>
          )}
        </TabsContent>

        {/* Activity tab */}
        <TabsContent value="activity" className="space-y-4 pt-4">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Activity</h2>

          {activityLoading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : activity.length === 0 ? (
            <p className="text-sm text-muted-foreground italic py-4">No activity recorded yet.</p>
          ) : (
            <div className="space-y-2">
              {activity.map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-start gap-3 p-3 rounded-md border border-border bg-card/50 text-sm"
                >
                  <div className="flex-shrink-0 mt-0.5">
                    <div className="h-2 w-2 rounded-full bg-[var(--brand-signal)] mt-1" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium capitalize">{entry.action.replace(/_/g, " ")}</span>
                      <span className="text-muted-foreground text-xs">
                        by {entry.user_sub ?? "system"}
                      </span>
                      <span className="text-muted-foreground text-xs ml-auto">
                        {fmtDate(entry.time)}
                      </span>
                    </div>
                    {entry.after_jsonb && Object.keys(entry.after_jsonb).length > 0 && (
                      <pre className="mt-1 text-xs text-muted-foreground font-mono whitespace-pre-wrap overflow-x-auto">
                        {JSON.stringify(entry.after_jsonb, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Attach Events dialog */}
      <AttachEventsDialog
        projectId={projectId}
        caseId={caseId}
        open={attachEventsOpen}
        onOpenChange={setAttachEventsOpen}
        onSuccess={() => void loadEvents(0)}
      />

      {/* Attach IOCs dialog */}
      <AttachIOCsDialog
        projectId={projectId}
        caseId={caseId}
        open={attachIOCsOpen}
        onOpenChange={setAttachIOCsOpen}
        onSuccess={() => void loadIOCs(0)}
      />
    </div>
  );
}
