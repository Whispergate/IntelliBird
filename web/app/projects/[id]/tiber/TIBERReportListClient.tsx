"use client";

/**
 * TIBERReportListClient — Surface 1 TIBER reports list.
 * UI-SPEC §Surface 1.
 *
 * Renders:
 *   - Page header with "TIBER Reports" heading + live count subtitle + "New report" CTA
 *   - Filter bar: status <Select> + show-archived <Switch>
 *   - shadcn <Table> with Title / CBEST / Status / Completeness / Last updated / Actions
 *   - Empty states (no reports / filters active with no results)
 *   - "New report" <Dialog> with title <Input> + CBEST <Switch>
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { FileSearch, FilterX, MoreHorizontal, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  archiveReport,
  cloneReport,
  createReport,
  listReports,
  publishReport,
  type TiberReport,
} from "./lib/api";
import { ReportStateBadge } from "./components/ReportStateBadge";

function formatRelativeTime(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(isoString).toLocaleDateString();
}

interface TIBERReportListClientProps {
  projectId: string;
}

export function TIBERReportListClient({ projectId }: TIBERReportListClientProps) {
  const router = useRouter();
  const sp = useSearchParams();

  const [reports, setReports] = useState<TiberReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>(sp.get("status") ?? "all");
  const [showArchived, setShowArchived] = useState(sp.get("archived") === "true");

  // New report dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newCbest, setNewCbest] = useState(false);
  const [creating, setCreating] = useState(false);

  const loadReports = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listReports({
        projectId,
        status: statusFilter === "all" ? undefined : statusFilter,
        includeArchived: showArchived,
      });
      setReports(data);
    } catch (e) {
      toast.error(`Failed to load reports. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [projectId, statusFilter, showArchived]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  // Sync URL params on filter change
  useEffect(() => {
    const params = new URLSearchParams();
    if (statusFilter !== "all") params.set("status", statusFilter);
    if (showArchived) params.set("archived", "true");
    const query = params.toString();
    router.replace(`/projects/${projectId}/tiber${query ? `?${query}` : ""}`);
  }, [statusFilter, showArchived, projectId, router]);

  async function onCreateReport() {
    if (!newTitle.trim()) return;
    setCreating(true);
    try {
      const report = await createReport({
        projectId,
        body: { title: newTitle.trim(), cbest_mode: newCbest },
      });
      setDialogOpen(false);
      setNewTitle("");
      setNewCbest(false);
      router.push(`/projects/${projectId}/tiber/${report.id}`);
    } catch (e) {
      toast.error(`Could not create report. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCreating(false);
    }
  }

  async function onClone(reportId: string) {
    try {
      const cloned = await cloneReport({ projectId, reportId });
      toast.success("Cloned to new draft.");
      router.push(`/projects/${projectId}/tiber/${cloned.id}`);
    } catch (e) {
      toast.error(`Could not clone. ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function onPublish(reportId: string) {
    try {
      await publishReport({ projectId, reportId });
      toast.success("Report published.");
      void loadReports();
    } catch (e) {
      toast.error(`Could not publish. ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function onArchive(reportId: string) {
    try {
      await archiveReport({ projectId, reportId });
      toast.success("Report archived.");
      void loadReports();
    } catch (e) {
      toast.error(`Could not archive. ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const draftCount = reports.filter((r) => r.state === "draft").length;
  const publishedCount = reports.filter((r) => r.state === "published").length;
  const filtersActive = statusFilter !== "all" || showArchived;

  return (
    <div className="max-w-5xl mx-auto px-4 pt-6 pb-12">
      {/* Page header */}
      <div className="flex items-baseline justify-between mb-4">
        <div>
          <h1 className="brand-heading">TIBER Reports</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {reports.length} report{reports.length !== 1 ? "s" : ""} &middot;{" "}
            {draftCount} draft, {publishedCount} published
          </p>
        </div>
        <Button
          variant="default"
          size="sm"
          onClick={() => setDialogOpen(true)}
        >
          <Plus size={14} className="mr-1" />
          New report
        </Button>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 items-center mb-4">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-40 h-8 text-sm">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="draft">Draft</SelectItem>
            <SelectItem value="published">Published</SelectItem>
            <SelectItem value="archived">Archived</SelectItem>
          </SelectContent>
        </Select>

        <div className="flex items-center gap-2">
          <Switch
            id="show-archived"
            checked={showArchived}
            onCheckedChange={setShowArchived}
          />
          <Label htmlFor="show-archived" className="text-sm text-muted-foreground cursor-pointer">
            Show archived
          </Label>
        </div>
      </div>

      {/* Reports table */}
      {loading ? (
        <div className="text-sm text-muted-foreground py-8 text-center">Loading reports…</div>
      ) : reports.length === 0 ? (
        filtersActive ? (
          <div className="py-12 flex flex-col items-center">
            <FilterX size={32} className="text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-muted-foreground text-sm text-center">
              No reports match these filters
            </p>
            <p className="text-xs text-muted-foreground text-center mt-1">
              Try changing the status filter or enabling &lsquo;Show archived&rsquo;.
            </p>
          </div>
        ) : (
          <div className="py-12 flex flex-col items-center">
            <FileSearch size={32} className="text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-muted-foreground text-sm text-center">No TIBER reports yet</p>
            <p className="text-xs text-muted-foreground text-center mt-1">
              Create a report to begin building a Targeted Threat Intelligence Report for this
              engagement.
            </p>
          </div>
        )
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead className="w-20">CBEST</TableHead>
              <TableHead className="w-24">Status</TableHead>
              <TableHead className="w-28">Completeness</TableHead>
              <TableHead className="w-32">Last updated</TableHead>
              <TableHead className="w-20">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {reports.map((report) => {
              // Completeness: count non-empty sections from report fields
              const completeSections = [
                report.engagement_window_start && report.engagement_window_end && report.in_scope_assets.length > 0,
                !!report.aia_summary_text && report.aia_recommendations.length > 0,
                report.tl_top_events.length > 0 && !!report.tl_analyst_narrative,
                false, // actor profiles — not in this response (fetched separately)
                false, // scenarios — not in this response
                !!report.scenario_x_narrative,
              ].filter(Boolean).length;

              return (
                <TableRow
                  key={report.id}
                  className="hover:bg-card/60 cursor-pointer"
                  onClick={() => router.push(`/projects/${projectId}/tiber/${report.id}`)}
                >
                  <TableCell className="font-medium text-sm">{report.title}</TableCell>
                  <TableCell>
                    {report.cbest_mode && (
                      <Badge
                        variant="outline"
                        className="bg-blue-500/15 text-blue-300 border-blue-600 brand-caption"
                      >
                        CBEST
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <ReportStateBadge state={report.state} />
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground">
                      {completeSections}/6 sections
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground">
                      {formatRelativeTime(report.updated_at)}
                    </span>
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0">
                          <MoreHorizontal size={14} />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() =>
                            router.push(`/projects/${projectId}/tiber/${report.id}`)
                          }
                        >
                          Open
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => onClone(report.id)}>
                          Clone to new draft
                        </DropdownMenuItem>
                        {report.state === "draft" && (
                          <DropdownMenuItem onClick={() => onPublish(report.id)}>
                            Publish
                          </DropdownMenuItem>
                        )}
                        {report.state === "published" && (
                          <DropdownMenuItem
                            onClick={() => onArchive(report.id)}
                            className="text-destructive"
                          >
                            Archive
                          </DropdownMenuItem>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      {/* New report dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>New TIBER report</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label htmlFor="new-report-title">Report title</Label>
              <Input
                id="new-report-title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="e.g. Q1 2026 TIBER engagement"
                onKeyDown={(e) => {
                  if (e.key === "Enter") void onCreateReport();
                }}
              />
            </div>
            <div className="flex items-center gap-3">
              <Switch
                id="new-report-cbest"
                checked={newCbest}
                onCheckedChange={setNewCbest}
              />
              <Label htmlFor="new-report-cbest" className="text-sm cursor-pointer">
                CBEST mode{" "}
                <span className="text-xs text-muted-foreground">(relabels CIF as CBS)</span>
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={onCreateReport} disabled={!newTitle.trim() || creating}>
              {creating ? "Creating…" : "Create report"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
