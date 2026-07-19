"use client";

import { useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  listCampaigns,
  createCampaign,
  deleteCampaign,
  type CampaignRead,
  type CampaignListResponse,
} from "@/app/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

function formatDate(value: string | null): string {
  if (!value) return "-";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "-";
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

interface CampaignsClientProps {
  projectId: string;
  initialData: CampaignListResponse;
}

export default function CampaignsClient({ projectId, initialData }: CampaignsClientProps) {
  const { data: session } = useSession();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const user = (session?.user as any) ?? null;
  const isLead =
    user?.role === "Lead" || user?.role === "Admin" ||
    user?.role === "lead" || user?.role === "admin";

  const [items, setItems] = useState<CampaignRead[]>(initialData.items);
  const [nextCursor, setNextCursor] = useState<string | null>(initialData.next_cursor);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({
    name: "",
    start_date: "",
    end_date: "",
    summary_md: "",
  });
  const [createError, setCreateError] = useState("");

  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listCampaigns(projectId);
      setItems(data.items);
      setNextCursor(data.next_cursor);
    } catch {
      toast.error("Failed to load campaigns.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  async function handleLoadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const res = await fetch(
        `/api/campaigns?project_id=${projectId}&limit=50&cursor=${nextCursor}`,
      );
      if (!res.ok) throw new Error();
      const data: CampaignListResponse = await res.json();
      setItems((prev) => [...prev, ...data.items]);
      setNextCursor(data.next_cursor);
    } catch {
      toast.error("Failed to load more campaigns.");
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!createForm.name.trim()) {
      setCreateError("Campaign name is required.");
      return;
    }
    setCreateError("");
    setCreating(true);
    try {
      await createCampaign({
        name: createForm.name.trim(),
        start_date: createForm.start_date || undefined,
        end_date: createForm.end_date || undefined,
        summary_md: createForm.summary_md.trim() || undefined,
        project_id: projectId,
      });
      setCreateOpen(false);
      setCreateForm({ name: "", start_date: "", end_date: "", summary_md: "" });
      await refresh();
    } catch {
      setCreateError("Failed to create campaign. Please try again.");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete campaign "${name}"? This cannot be undone.`)) return;
    setDeletingId(id);
    try {
      await deleteCampaign(id);
      setItems((prev) => prev.filter((c) => c.id !== id));
      toast.success("Campaign deleted.");
    } catch {
      toast.error("Failed to delete campaign.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-0">
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 border-b border-border"
          style={{ minHeight: 56 }}
        >
          <div>
            <h1 className="text-[22px] font-medium leading-tight">Campaigns</h1>
            <p className="text-sm text-muted-foreground">
              Threat campaigns scoped to this project
            </p>
          </div>
          {isLead && (
            <Button
              onClick={() => setCreateOpen(true)}
              className="bg-[var(--brand-signal)] hover:bg-[var(--brand-signal)]/90 text-[#0D1B2A] font-medium"
            >
              <Plus className="h-4 w-4 mr-1" />
              New Campaign
            </Button>
          )}
        </div>

        {/* Table */}
        <div className="px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="animate-spin h-4 w-4 text-teal-400" />
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-2">
              <h2 className="text-lg font-medium">No campaigns yet</h2>
              <p className="text-sm text-muted-foreground">
                {isLead
                  ? "Create a campaign to group related threat activity."
                  : "No campaigns have been created for this project."}
              </p>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead style={{ width: 120 }}>Start</TableHead>
                    <TableHead style={{ width: 120 }}>End</TableHead>
                    <TableHead>Summary</TableHead>
                    <TableHead style={{ width: 80 }}>Scope</TableHead>
                    {isLead && (
                      <TableHead style={{ width: 48 }}>
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((campaign) => (
                    <TableRow key={campaign.id} className="hover:bg-card/50">
                      <TableCell className="font-medium">{campaign.name}</TableCell>
                      <TableCell>{formatDate(campaign.start_date)}</TableCell>
                      <TableCell>{formatDate(campaign.end_date)}</TableCell>
                      <TableCell className="text-muted-foreground truncate" style={{ maxWidth: "40ch" }}>
                        {campaign.summary_md
                          ? campaign.summary_md.slice(0, 120) +
                            (campaign.summary_md.length > 120 ? "…" : "")
                          : "-"}
                      </TableCell>
                      <TableCell>
                        <span className="text-xs text-muted-foreground">
                          {campaign.project_id ? "Project" : "Global"}
                        </span>
                      </TableCell>
                      {isLead && (
                        <TableCell>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                disabled={deletingId === campaign.id}
                                onClick={() => handleDelete(campaign.id, campaign.name)}
                                aria-label="Delete campaign"
                              >
                                {deletingId === campaign.id ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <Trash2 className="h-4 w-4" />
                                )}
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Delete campaign</TooltipContent>
                          </Tooltip>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {nextCursor && (
                <div className="flex justify-center mt-4">
                  <Button variant="outline" onClick={handleLoadMore} disabled={loadingMore}>
                    {loadingMore ? (
                      <Loader2 className="animate-spin h-4 w-4 mr-2" />
                    ) : null}
                    Show more
                  </Button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Create dialog */}
        {isLead && (
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>New Campaign</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleCreate} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="campaign-name">Name *</Label>
                  <Input
                    id="campaign-name"
                    placeholder="e.g. Operation Cobalt Strike 2025"
                    value={createForm.name}
                    onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
                    required
                  />
                  {createError && (
                    <p className="text-destructive text-sm">{createError}</p>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="campaign-start">Start Date</Label>
                    <Input
                      id="campaign-start"
                      type="date"
                      value={createForm.start_date}
                      onChange={(e) =>
                        setCreateForm((f) => ({ ...f, start_date: e.target.value }))
                      }
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="campaign-end">End Date</Label>
                    <Input
                      id="campaign-end"
                      type="date"
                      value={createForm.end_date}
                      onChange={(e) =>
                        setCreateForm((f) => ({ ...f, end_date: e.target.value }))
                      }
                    />
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="campaign-summary">Summary</Label>
                  <Textarea
                    id="campaign-summary"
                    placeholder="Brief campaign description (Markdown supported)…"
                    value={createForm.summary_md}
                    onChange={(e) =>
                      setCreateForm((f) => ({ ...f, summary_md: e.target.value }))
                    }
                    style={{ minHeight: 80 }}
                  />
                </div>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => {
                      setCreateOpen(false);
                      setCreateError("");
                    }}
                  >
                    Discard
                  </Button>
                  <Button
                    type="submit"
                    disabled={creating || !createForm.name.trim()}
                    className="bg-teal-600 hover:bg-teal-500 text-white"
                  >
                    {creating ? (
                      <Loader2 className="animate-spin h-4 w-4 mr-2" />
                    ) : null}
                    Create
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>
    </TooltipProvider>
  );
}
