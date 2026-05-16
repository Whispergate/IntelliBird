"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { Loader2, Pencil } from "lucide-react";

import {
  patchActor,
  listCampaigns,
  patchCampaign,
  type ActorRead,
  type CampaignRead,
} from "@/app/api-client";
import { SophisticationBadge } from "@/app/actors/badges";
import { CampaignCard } from "./CampaignCard";
import { CampaignDialog } from "./CampaignDialog";
import { ActorSubGraph } from "./ActorSubGraph";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { type Tier } from "@/lib/scoring";
import { TierBadge } from "@/app/components/TierBadge";

const SOPHISTICATION_OPTIONS = [
  "minimal",
  "intermediate",
  "advanced",
  "expert",
  "unknown",
] as const;

const DATE_RANGE_OPTIONS = [
  { label: "Last 30d", days: 30 },
  { label: "Last 90d", days: 90 },
  { label: "Last 6mo", days: 180 },
  { label: "Last 1yr", days: 365 },
  { label: "All time", days: 0 },
] as const;

interface ActorProfileClientProps {
  actor: ActorRead;
}

interface EventCard {
  id: string;
  title: string;
  tier: string;
  observed_at: string;
  source_name?: string;
}

export default function ActorProfileClient({ actor: initialActor }: ActorProfileClientProps) {
  const { data: session } = useSession();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const user = (session?.user as any) ?? null;
  const isLead =
    user?.role === "lead" ||
    user?.role === "admin" ||
    user?.role === "Lead" ||
    user?.role === "Admin";

  // Actor state (may be updated by edit panel)
  const [actor, setActor] = useState<ActorRead>(initialActor);

  // Edit panel
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState({
    primary_name: actor.primary_name,
    aliases_raw: (actor.aliases ?? []).join(", "),
    country: actor.country ?? "",
    motivation: actor.motivation ?? "",
    sophistication: actor.sophistication ?? "",
    profile_md: actor.profile_md ?? "",
  });
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState("");

  // Alias chip tag editor
  const [aliasInput, setAliasInput] = useState("");
  const [aliases, setAliases] = useState<string[]>(actor.aliases ?? []);

  // Events timeline
  const [dateRangeDays, setDateRangeDays] = useState(90);
  const [events, setEvents] = useState<EventCard[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsShowMore, setEventsShowMore] = useState(false);
  const [eventsShown, setEventsShown] = useState(20);

  // Campaigns
  const [campaigns, setCampaigns] = useState<CampaignRead[]>([]);
  const [campaignsLoading, setCampaignsLoading] = useState(false);
  const [campaignDialogOpen, setCampaignDialogOpen] = useState(false);

  // Load campaigns on mount
  useEffect(() => {
    setCampaignsLoading(true);
    fetch(`/api/actors/${actor.id}/campaigns`)
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((data) => setCampaigns(data.items ?? []))
      .catch(() => setCampaigns([]))
      .finally(() => setCampaignsLoading(false));
  }, [actor.id]);

  // Load events when dateRangeDays changes
  useEffect(() => {
    setEventsLoading(true);
    const query = dateRangeDays > 0 ? `?days=${dateRangeDays}` : "";
    fetch(`/api/actors/${actor.id}/events${query}`)
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((data) => {
        const items = data.items ?? [];
        setEvents(items);
        setEventsShown(20);
        setEventsShowMore(items.length > 20);
      })
      .catch(() => setEvents([]))
      .finally(() => setEventsLoading(false));
  }, [actor.id, dateRangeDays]);

  // Sync edit form when actor changes
  useEffect(() => {
    setEditForm({
      primary_name: actor.primary_name,
      aliases_raw: (actor.aliases ?? []).join(", "),
      country: actor.country ?? "",
      motivation: actor.motivation ?? "",
      sophistication: actor.sophistication ?? "",
      profile_md: actor.profile_md ?? "",
    });
    setAliases(actor.aliases ?? []);
  }, [actor]);

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editForm.primary_name.trim() || editForm.primary_name.trim().length < 2) {
      setEditError("Actor name is required (minimum 2 characters).");
      return;
    }
    setEditError("");
    setEditSaving(true);
    try {
      const updated = await patchActor(actor.id, {
        primary_name: editForm.primary_name.trim(),
        aliases: aliases.length > 0 ? aliases : null,
        country: editForm.country.trim() || null,
        motivation: editForm.motivation.trim() || null,
        sophistication: editForm.sophistication || null,
        profile_md: editForm.profile_md.trim() || null,
      });
      setActor(updated);
      setEditOpen(false);
    } catch {
      setEditError("Failed to save. Please try again.");
    } finally {
      setEditSaving(false);
    }
  }

  function handleAliasKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const val = aliasInput.trim().replace(/,$/, "");
      if (val && !aliases.includes(val)) {
        setAliases((prev) => [...prev, val]);
      }
      setAliasInput("");
    }
  }

  function removeAlias(alias: string) {
    setAliases((prev) => prev.filter((a) => a !== alias));
  }

  function handleCampaignCreated(campaign: CampaignRead) {
    setCampaigns((prev) => [campaign, ...prev]);
  }

  async function handleUnlinkCampaign(campaignId: string) {
    try {
      await patchCampaign(campaignId, { actor_id: null });
      setCampaigns((prev) => prev.filter((c) => c.id !== campaignId));
    } catch {
      // silent — could show toast
    }
  }

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-6 p-6">
        {/* Header section */}
        <div className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-[22px] font-medium leading-tight">{actor.primary_name}</h1>
            {isLead && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditOpen((v) => !v)}
                className="shrink-0"
                aria-label="Edit actor"
              >
                <Pencil className="h-4 w-4 mr-1" />
                Edit Profile
              </Button>
            )}
          </div>

          {/* Aliases row */}
          {actor.aliases && actor.aliases.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {actor.aliases.map((alias) => (
                <span
                  key={alias}
                  className="font-mono text-[12px] bg-card border border-border text-muted-foreground px-2 py-1 rounded"
                >
                  {alias}
                </span>
              ))}
            </div>
          )}

          {/* Metadata row */}
          <div className="flex flex-wrap items-center gap-2">
            {actor.country && (
              <span className="text-[12px] font-medium bg-card border border-border px-2 py-1 rounded">
                {actor.country}
              </span>
            )}
            {actor.motivation && (
              <span className="text-[12px] font-medium bg-card border border-border px-2 py-1 rounded text-muted-foreground">
                {actor.motivation}
              </span>
            )}
            <SophisticationBadge value={actor.sophistication} />
            {actor.mitre_group_id && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <a
                    href={`https://attack.mitre.org/groups/${actor.mitre_group_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-[12px] bg-card border border-border px-2 py-1 rounded text-teal-400 hover:text-teal-300"
                  >
                    {actor.mitre_group_id}
                  </a>
                </TooltipTrigger>
                <TooltipContent>View on ATT&CK</TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>

        {/* Inline edit panel (Lead+ only) */}
        {isLead && editOpen && (
          <Card className="border-teal-700">
            <CardContent className="p-4">
              <form onSubmit={handleSaveEdit} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="edit-name">Primary Name *</Label>
                  <Input
                    id="edit-name"
                    value={editForm.primary_name}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, primary_name: e.target.value }))
                    }
                    required
                  />
                  {editError && (
                    <p className="text-destructive text-sm">{editError}</p>
                  )}
                </div>

                {/* Alias tag editor */}
                <div className="flex flex-col gap-1">
                  <Label>Aliases</Label>
                  <div className="flex flex-wrap gap-1 p-2 border rounded-md bg-background min-h-[40px]">
                    {aliases.map((alias) => (
                      <span
                        key={alias}
                        className="inline-flex items-center gap-1 font-mono text-[12px] bg-card border border-border px-2 py-0.5 rounded text-muted-foreground"
                      >
                        {alias}
                        <button
                          type="button"
                          onClick={() => removeAlias(alias)}
                          className="hover:text-destructive"
                          aria-label={`Remove alias ${alias}`}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                    <input
                      type="text"
                      placeholder="Add alias, press Enter…"
                      value={aliasInput}
                      onChange={(e) => setAliasInput(e.target.value)}
                      onKeyDown={handleAliasKeyDown}
                      className="flex-1 min-w-[140px] bg-transparent outline-none text-sm"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="edit-country">Country</Label>
                    <Input
                      id="edit-country"
                      value={editForm.country}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, country: e.target.value }))
                      }
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="edit-motivation">Motivation</Label>
                    <Input
                      id="edit-motivation"
                      value={editForm.motivation}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, motivation: e.target.value }))
                      }
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-1">
                  <Label htmlFor="edit-sophistication">Sophistication</Label>
                  <Select
                    value={editForm.sophistication || "unknown"}
                    onValueChange={(v) =>
                      setEditForm((f) => ({
                        ...f,
                        sophistication: v === "unknown" ? "" : v,
                      }))
                    }
                  >
                    <SelectTrigger id="edit-sophistication">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SOPHISTICATION_OPTIONS.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s.charAt(0).toUpperCase() + s.slice(1)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex flex-col gap-1">
                  <Label htmlFor="edit-profile">Profile Notes (Markdown)</Label>
                  <Textarea
                    id="edit-profile"
                    value={editForm.profile_md}
                    onChange={(e) =>
                      setEditForm((f) => ({ ...f, profile_md: e.target.value }))
                    }
                    style={{ minHeight: 120 }}
                  />
                </div>

                <div className="flex gap-2 justify-end">
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setEditOpen(false)}
                  >
                    Discard
                  </Button>
                  <Button
                    type="submit"
                    disabled={editSaving || editForm.primary_name.trim().length < 2}
                    className="bg-teal-600 hover:bg-teal-500 text-white"
                  >
                    {editSaving ? (
                      <Loader2 className="animate-spin h-4 w-4 mr-2" />
                    ) : null}
                    Save
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        <Separator />

        {/* Two-column layout at xl */}
        <div className="grid grid-cols-1 xl:grid-cols-[40%_60%] gap-6">
          {/* Left column — profile info, events, campaigns */}
          <div className="flex flex-col gap-8">

            {/* Events Timeline */}
            <section>
              <div className="flex items-center justify-between gap-3 mb-3">
                <h2 className="text-[22px] font-medium">Associated Events</h2>
                <Select
                  value={String(dateRangeDays)}
                  onValueChange={(v) => setDateRangeDays(Number(v))}
                >
                  <SelectTrigger className="w-36">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DATE_RANGE_OPTIONS.map((o) => (
                      <SelectItem key={o.days} value={String(o.days)}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {eventsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="animate-spin h-5 w-5 text-teal-400" />
                </div>
              ) : events.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No events in this date range linked to this actor.
                </p>
              ) : (
                <div className="flex flex-col gap-2">
                  {events.slice(0, eventsShown).map((ev) => (
                    <Card key={ev.id} className="bg-card">
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex flex-col gap-1 flex-1 min-w-0">
                            <span className="text-sm font-medium truncate">
                              {ev.title}
                            </span>
                            <div className="flex items-center gap-2 flex-wrap">
                              {ev.tier && (
                                <TierBadge tier={ev.tier as Tier} />
                              )}
                              <span className="text-[12px] text-muted-foreground">
                                {new Date(ev.observed_at).toLocaleDateString("en-US", {
                                  month: "short",
                                  day: "numeric",
                                  year: "numeric",
                                })}
                              </span>
                              {ev.source_name && (
                                <span className="text-[12px] bg-card border border-border px-2 py-0.5 rounded text-muted-foreground">
                                  {ev.source_name}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                  {eventsShowMore && eventsShown < events.length && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEventsShown((n) => n + 20)}
                    >
                      Show more
                    </Button>
                  )}
                </div>
              )}
            </section>

            {/* Campaigns Section */}
            <section>
              <div className="flex items-center justify-between gap-3 mb-3">
                <h2 className="text-[22px] font-medium">Campaigns</h2>
                {isLead && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCampaignDialogOpen(true)}
                  >
                    Link Campaign
                  </Button>
                )}
              </div>

              {campaignsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="animate-spin h-5 w-5 text-teal-400" />
                </div>
              ) : campaigns.length === 0 ? (
                <div className="flex flex-col items-start gap-3">
                  <p className="text-sm text-muted-foreground">
                    No campaigns linked to this actor.
                  </p>
                  {isLead && (
                    <Button
                      onClick={() => setCampaignDialogOpen(true)}
                      className="bg-[var(--brand-signal)] hover:bg-[var(--brand-signal)]/90 text-[#0D1B2A] font-medium"
                    >
                      Create Campaign
                    </Button>
                  )}
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {campaigns.map((campaign) => (
                    <CampaignCard
                      key={campaign.id}
                      campaign={campaign}
                      onUnlink={
                        isLead ? () => handleUnlinkCampaign(campaign.id) : undefined
                      }
                    />
                  ))}
                </div>
              )}
            </section>
          </div>

          {/* Right column — Cytoscape sub-graph */}
          <div>
            <ActorSubGraph actorId={actor.id} />
          </div>
        </div>
      </div>

      {/* Campaign create dialog */}
      {isLead && (
        <CampaignDialog
          actorId={actor.id}
          open={campaignDialogOpen}
          onOpenChange={setCampaignDialogOpen}
          onCreated={handleCampaignCreated}
        />
      )}
    </TooltipProvider>
  );
}
