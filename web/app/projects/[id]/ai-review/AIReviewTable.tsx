"use client";

/**
 * AIReviewTable — Phase 17 plan 17-08.
 * UI-SPEC §Surface 2 — /projects/[id]/ai-review suggestion queue.
 *
 * Features:
 *   - URL param sync (?type=, ?status=, ?since=)
 *   - Three shadcn Selects (type / status / since)
 *   - shadcn Table with columns: checkbox | entity_value | type | status | event | created | actions
 *   - Row checkbox + select-all header checkbox
 *   - Sticky selection bar when selected.length > 0
 *   - Bulk confirm: POST /api/projects/{id}/ai/suggestions/bulk-confirm
 *   - Bulk discard: window.confirm with exact UI-SPEC copy
 *   - Per-row Confirm/Discard ghost buttons (pending rows only)
 *   - Empty state with Inbox icon + exact UI-SPEC copy
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Inbox } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatRelativeTime } from "@/app/sources/lib/relativeTime";
import type { AISuggestionRead } from "@/app/api-client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SuggestionType = "all" | "cve" | "attack" | "actor";
type SuggestionStatus = "all" | "pending" | "confirmed" | "discarded";
type SincePeriod = "all" | "24h" | "7d" | "30d";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function typeBadgeClass(t: string): string {
  switch (t) {
    case "cve":
      return "bg-blue-900/40 text-blue-300 border-blue-700";
    case "attack":
      return "bg-orange-900/40 text-orange-300 border-orange-700";
    case "actor":
      return "bg-purple-900/40 text-purple-300 border-purple-700";
    default:
      return "";
  }
}

function statusBadgeClass(s: string): string {
  switch (s) {
    case "pending":
      return "bg-yellow-500/10 text-yellow-300 border-yellow-600";
    case "confirmed":
      return "bg-green-500/10 text-green-300 border-green-700";
    case "discarded":
      return "bg-muted text-muted-foreground border-muted-foreground/40";
    default:
      return "";
  }
}

function typeLabelMap(t: string): string {
  switch (t) {
    case "cve":
      return "CVE";
    case "attack":
      return "ATT&CK";
    case "actor":
      return "Actor";
    default:
      return t;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AIReviewTable({ projectId }: { projectId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Filters from URL
  const [typeFilter, setTypeFilter] = useState<SuggestionType>(
    (searchParams.get("type") as SuggestionType) ?? "all",
  );
  const [statusFilter, setStatusFilter] = useState<SuggestionStatus>(
    (searchParams.get("status") as SuggestionStatus) ?? "pending",
  );
  const [sinceFilter, setSinceFilter] = useState<SincePeriod>(
    (searchParams.get("since") as SincePeriod) ?? "all",
  );

  const [suggestions, setSuggestions] = useState<AISuggestionRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [pendingTotal, setPendingTotal] = useState(0);

  // Multi-select
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // ---------------------------------------------------------------------------
  // URL sync
  // ---------------------------------------------------------------------------

  function syncUrl(
    newType: SuggestionType,
    newStatus: SuggestionStatus,
    newSince: SincePeriod,
  ) {
    const params = new URLSearchParams();
    if (newType !== "all") params.set("type", newType);
    if (newStatus !== "all") params.set("status", newStatus);
    if (newSince !== "all") params.set("since", newSince);
    const query = params.toString() ? `?${params.toString()}` : "";
    router.push(`${pathname}${query}`);
  }

  function handleTypeChange(v: SuggestionType) {
    setTypeFilter(v);
    syncUrl(v, statusFilter, sinceFilter);
    setSelected(new Set());
  }

  function handleStatusChange(v: SuggestionStatus) {
    setStatusFilter(v);
    syncUrl(typeFilter, v, sinceFilter);
    setSelected(new Set());
  }

  function handleSinceChange(v: SincePeriod) {
    setSinceFilter(v);
    syncUrl(typeFilter, statusFilter, v);
    setSelected(new Set());
  }

  // ---------------------------------------------------------------------------
  // Data fetch
  // ---------------------------------------------------------------------------

  const fetchSuggestions = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (typeFilter !== "all") params.set("type", typeFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (sinceFilter !== "all") params.set("since", sinceFilter);
      const query = params.toString() ? `?${params.toString()}` : "";

      const res = await fetch(
        `/api/projects/${projectId}/ai/suggestions${query}`,
        { credentials: "include" },
      );
      if (!res.ok) {
        toast.error("Could not load suggestion queue. Check your connection and refresh.");
        return;
      }
      const data: AISuggestionRead[] = await res.json();
      setSuggestions(data);

      // Fetch total pending (unfiltered) for page subtitle
      const pendingRes = await fetch(
        `/api/projects/${projectId}/ai/suggestions?status=pending`,
        { credentials: "include" },
      );
      if (pendingRes.ok) {
        const pendingData: AISuggestionRead[] = await pendingRes.json();
        setPendingTotal(pendingData.length);
      }
    } catch {
      toast.error("Could not load suggestion queue. Check your connection and refresh.");
    } finally {
      setLoading(false);
    }
  }, [projectId, typeFilter, statusFilter, sinceFilter]);

  useEffect(() => {
    fetchSuggestions();
  }, [fetchSuggestions]);

  // ---------------------------------------------------------------------------
  // Selection
  // ---------------------------------------------------------------------------

  const allIds = suggestions.map((s) => s.id);
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id));
  const someSelected = selected.size > 0;

  function toggleAll(checked: boolean) {
    setSelected(checked ? new Set(allIds) : new Set());
  }

  function toggleRow(id: string, checked: boolean) {
    const next = new Set(selected);
    if (checked) next.add(id);
    else next.delete(id);
    setSelected(next);
  }

  // ---------------------------------------------------------------------------
  // Bulk actions
  // ---------------------------------------------------------------------------

  async function handleBulkConfirm() {
    const ids = Array.from(selected);
    const count = ids.length;
    try {
      const res = await fetch(
        `/api/projects/${projectId}/ai/suggestions/bulk-confirm`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        },
      );
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        toast.error(`Could not complete bulk action. ${text || "Unknown error."}`);
        return;
      }
      toast.success(`${count} suggestions confirmed.`);
      setSelected(new Set());
      fetchSuggestions();
    } catch {
      toast.error("Could not complete bulk action. Check your connection and refresh.");
    }
  }

  async function handleBulkDiscard() {
    const ids = Array.from(selected);
    const count = ids.length;
    const confirmed = window.confirm(
      `Discard ${count} suggestions? This cannot be undone.`,
    );
    if (!confirmed) return;

    try {
      const res = await fetch(
        `/api/projects/${projectId}/ai/suggestions/bulk-discard`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        },
      );
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        toast.error(`Could not complete bulk action. ${text || "Unknown error."}`);
        return;
      }
      toast.success(`${count} suggestions discarded.`);
      setSelected(new Set());
      fetchSuggestions();
    } catch {
      toast.error("Could not complete bulk action. Check your connection and refresh.");
    }
  }

  // ---------------------------------------------------------------------------
  // Per-row actions
  // ---------------------------------------------------------------------------

  async function handleRowConfirm(id: string) {
    try {
      const res = await fetch(`/api/ai/suggestions/${id}/confirm`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(String(res.status));
      setSuggestions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, status: "confirmed" } : s)),
      );
    } catch {
      toast.error("Could not confirm suggestion.");
    }
  }

  async function handleRowDiscard(id: string) {
    try {
      const res = await fetch(`/api/ai/suggestions/${id}/discard`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error(String(res.status));
      setSuggestions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, status: "discarded" } : s)),
      );
    } catch {
      toast.error("Could not discard suggestion.");
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="max-w-5xl mx-auto pt-6">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="brand-heading text-2xl font-medium">
          AI Suggestion Queue
        </h1>
        <p className="text-muted-foreground mt-1" style={{ fontSize: 16 }}>
          {pendingTotal} pending suggestions across all events
        </p>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 items-center mb-4">
        <Select value={typeFilter} onValueChange={handleTypeChange}>
          <SelectTrigger className="w-44" aria-label="Filter by type">
            <SelectValue placeholder="All types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            <SelectItem value="cve">CVE</SelectItem>
            <SelectItem value="attack">ATT&CK Technique</SelectItem>
            <SelectItem value="actor">Threat Actor</SelectItem>
          </SelectContent>
        </Select>

        <Select value={statusFilter} onValueChange={handleStatusChange}>
          <SelectTrigger className="w-44" aria-label="Filter by status">
            <SelectValue placeholder="Pending" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="confirmed">Confirmed</SelectItem>
            <SelectItem value="discarded">Discarded</SelectItem>
            <SelectItem value="all">All</SelectItem>
          </SelectContent>
        </Select>

        <Select value={sinceFilter} onValueChange={handleSinceChange}>
          <SelectTrigger className="w-44" aria-label="Filter by date">
            <SelectValue placeholder="All time" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="24h">Last 24h</SelectItem>
            <SelectItem value="7d">Last 7 days</SelectItem>
            <SelectItem value="30d">Last 30 days</SelectItem>
            <SelectItem value="all">All time</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Selection count bar — visible when rows are selected */}
      {someSelected && (
        <div
          className="flex items-center justify-between bg-card border border-border rounded-md px-4 py-2 mb-3"
          data-testid="selection-bar"
        >
          <span className="text-sm">
            {selected.size} suggestion{selected.size !== 1 ? "s" : ""} selected
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="default" onClick={handleBulkConfirm}>
              Confirm selected
            </Button>
            <Button size="sm" variant="destructive" onClick={handleBulkDiscard}>
              Discard selected
            </Button>
          </div>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="flex flex-col gap-2" aria-label="Loading suggestions">
          {[1, 2, 3].map((n) => (
            <div key={n} className="animate-pulse bg-muted rounded h-10 w-full" />
          ))}
        </div>
      ) : suggestions.length === 0 ? (
        /* Empty state — UI-SPEC §Copywriting Contract */
        <div className="flex flex-col items-center justify-center py-16">
          <Inbox size={32} className="text-muted-foreground/40 mx-auto mb-2" />
          <p className="text-muted-foreground text-sm text-center">
            No suggestions match these filters
          </p>
          <p className="text-xs text-muted-foreground text-center mt-1">
            Adjust the filters above, or run &apos;Summarise&apos; on events to generate new
            suggestions.
          </p>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <Checkbox
                  checked={allSelected}
                  onCheckedChange={(v) => toggleAll(!!v)}
                  aria-label="Select all suggestions"
                />
              </TableHead>
              <TableHead>Entity</TableHead>
              <TableHead className="w-28">Type</TableHead>
              <TableHead className="w-24">Status</TableHead>
              <TableHead>Event</TableHead>
              <TableHead className="w-28">Created</TableHead>
              <TableHead className="w-20">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {suggestions.map((s) => (
              <TableRow key={s.id} className="hover:bg-card/60">
                <TableCell>
                  <Checkbox
                    checked={selected.has(s.id)}
                    onCheckedChange={(v) => toggleRow(s.id, !!v)}
                    aria-label={`Select suggestion ${s.value}`}
                  />
                </TableCell>
                <TableCell>
                  <span
                    className="font-mono text-sm truncate block max-w-[240px]"
                    title={s.value}
                  >
                    {s.value}
                  </span>
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={`brand-caption uppercase ${typeBadgeClass(s.suggestion_type)}`}
                  >
                    {typeLabelMap(s.suggestion_type)}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={`brand-caption ${statusBadgeClass(s.status)}`}
                  >
                    {s.status.charAt(0).toUpperCase() + s.status.slice(1)}
                  </Badge>
                </TableCell>
                <TableCell>
                  {s.event_id ? (
                    <a
                      href={`?event=${s.event_id}`}
                      className="text-sm text-muted-foreground hover:text-foreground truncate block max-w-[200px]"
                      title={s.event_id}
                    >
                      {s.event_id}
                    </a>
                  ) : (
                    <span className="text-muted-foreground text-sm">—</span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatRelativeTime(s.created_at)}
                </TableCell>
                <TableCell>
                  {s.status === "pending" && (
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRowConfirm(s.id)}
                        aria-label={`Confirm ${s.value}`}
                      >
                        Confirm
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRowDiscard(s.id)}
                        aria-label={`Discard ${s.value}`}
                      >
                        Discard
                      </Button>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
