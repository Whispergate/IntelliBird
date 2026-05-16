"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { Loader2, Pencil, Plus } from "lucide-react";

import {
  listActors,
  createActor,
  type ActorRead,
  type ActorListResponse,
} from "@/app/api-client";
import { SophisticationBadge } from "./badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const SOPHISTICATION_OPTIONS = [
  "minimal",
  "intermediate",
  "advanced",
  "expert",
  "unknown",
] as const;

interface ActorsClientProps {
  initialData: ActorListResponse | null;
}

// Format first_seen "2023-01-15T..." → "Jan 2023"
function formatFirstSeen(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

// Flag emoji from country name (very approximate — based on country codes embedded in names)
function countryDisplay(country: string | null): string {
  if (!country) return "—";
  return country;
}

export default function ActorsClient({ initialData }: ActorsClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: session } = useSession();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const user = (session?.user as any) ?? null;
  const isLead = user?.role === "lead" || user?.role === "admin" || user?.role === "Lead" || user?.role === "Admin";

  // Filter state
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  const [country, setCountry] = useState(searchParams?.get("country") ?? "");
  const [sophistication, setSophistication] = useState(
    searchParams?.get("sophistication") ?? "",
  );

  // Data state
  const [items, setItems] = useState<ActorRead[]>(initialData?.items ?? []);
  const [nextCursor, setNextCursor] = useState<string | null>(
    initialData?.next_cursor ?? null,
  );
  const [total, setTotal] = useState<number | null>(initialData?.total ?? null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  // Debounce ref
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Create actor dialog state
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({
    primary_name: "",
    aliases_raw: "",
    country: "",
    motivation: "",
    sophistication: "",
    profile_md: "",
  });
  const [createError, setCreateError] = useState("");

  // Sync URL params
  const syncURL = useCallback(
    (newQ: string, newCountry: string, newSoph: string) => {
      const params = new URLSearchParams();
      if (newQ) params.set("q", newQ);
      if (newCountry) params.set("country", newCountry);
      if (newSoph) params.set("sophistication", newSoph);
      router.replace(`/actors?${params.toString()}`);
    },
    [router],
  );

  // Fetch with current filters
  const fetchActors = useCallback(
    async (overrideQ?: string, overrideCountry?: string, overrideSoph?: string) => {
      const resolvedQ = overrideQ ?? q;
      const resolvedCountry = overrideCountry ?? country;
      const resolvedSoph = overrideSoph ?? sophistication;
      setLoading(true);
      try {
        const data = await listActors({
          q: resolvedQ || undefined,
          country: resolvedCountry || undefined,
          sophistication: resolvedSoph || undefined,
          limit: 50,
        });
        setItems(data.items);
        setNextCursor(data.next_cursor);
        setTotal(data.total);
      } catch {
        setItems([]);
        setNextCursor(null);
      } finally {
        setLoading(false);
      }
    },
    [q, country, sophistication],
  );

  // Debounced search
  function handleSearchChange(value: string) {
    setQ(value);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      syncURL(value, country, sophistication);
      fetchActors(value, country, sophistication);
    }, 300);
  }

  function handleCountryChange(value: string) {
    const v = value === "all" ? "" : value;
    setCountry(v);
    syncURL(q, v, sophistication);
    fetchActors(q, v, sophistication);
  }

  function handleSophisticationChange(value: string) {
    const v = value === "all" ? "" : value;
    setSophistication(v);
    syncURL(q, country, v);
    fetchActors(q, country, v);
  }

  // Load more (cursor pagination)
  async function handleLoadMore() {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const data = await listActors({
        q: q || undefined,
        country: country || undefined,
        sophistication: sophistication || undefined,
        limit: 50,
        cursor: nextCursor,
      });
      setItems((prev) => [...prev, ...data.items]);
      setNextCursor(data.next_cursor);
    } catch {
      // silent
    } finally {
      setLoadingMore(false);
    }
  }

  // Create actor submit
  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!createForm.primary_name.trim() || createForm.primary_name.trim().length < 2) {
      setCreateError("Actor name is required (minimum 2 characters).");
      return;
    }
    setCreateError("");
    setCreating(true);
    try {
      const aliases =
        createForm.aliases_raw
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean);
      await createActor({
        primary_name: createForm.primary_name.trim(),
        aliases: aliases.length > 0 ? aliases : null,
        country: createForm.country.trim() || null,
        motivation: createForm.motivation.trim() || null,
        sophistication: createForm.sophistication || null,
        first_seen: null,
        profile_md: createForm.profile_md.trim() || null,
      });
      setCreateOpen(false);
      setCreateForm({
        primary_name: "",
        aliases_raw: "",
        country: "",
        motivation: "",
        sophistication: "",
        profile_md: "",
      });
      // Refresh list
      fetchActors();
    } catch {
      setCreateError("Failed to create actor. Please try again.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-0">
        {/* Page header */}
        <div
          className="flex items-center justify-between px-6 py-4 border-b border-border"
          style={{ minHeight: 56 }}
        >
          <div>
            <h1 className="text-[22px] font-medium leading-tight">Threat Actors</h1>
            <p className="text-sm text-muted-foreground">
              Global catalog — survives across engagements
            </p>
          </div>
          {isLead && (
            <Button
              onClick={() => setCreateOpen(true)}
              className="bg-[var(--brand-signal)] hover:bg-[var(--brand-signal)]/90 text-[#0D1B2A] font-medium"
            >
              <Plus className="h-4 w-4 mr-1" />
              Create Actor
            </Button>
          )}
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-border flex-wrap">
          <Input
            placeholder="Search by name or alias…"
            value={q}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="w-80"
          />
          <Select
            value={country || "all"}
            onValueChange={handleCountryChange}
          >
            <SelectTrigger className="w-44">
              <SelectValue placeholder="All countries" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All countries</SelectItem>
              {/* Countries are dynamic — only "all" available until actors are loaded */}
              {Array.from(new Set(items.map((a) => a.country).filter(Boolean))).map(
                (c) => (
                  <SelectItem key={c!} value={c!}>
                    {c}
                  </SelectItem>
                ),
              )}
            </SelectContent>
          </Select>
          <Select
            value={sophistication || "all"}
            onValueChange={handleSophisticationChange}
          >
            <SelectTrigger className="w-44">
              <SelectValue placeholder="All sophistication" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {SOPHISTICATION_OPTIONS.map((s) => (
                <SelectItem key={s} value={s}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Table */}
        <div className="px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="animate-spin h-4 w-4 text-teal-400" />
            </div>
          ) : items.length === 0 ? (
            <div className="flex items-center justify-center py-16">
              <Card className="max-w-md w-full">
                <CardContent className="pt-6 text-center">
                  <h2 className="text-lg font-medium mb-2">No threat actors yet</h2>
                  <p className="text-sm text-muted-foreground mb-4">
                    Run the MITRE bootstrap from Admin &gt; Maintenance to import the
                    ATT&amp;CK catalog, or create an actor manually.
                  </p>
                  <Button variant="outline" asChild>
                    <Link href="/admin/maintenance">Go to Maintenance</Link>
                  </Button>
                </CardContent>
              </Card>
            </div>
          ) : (
            <>
              {total !== null && (
                <p className="text-sm text-muted-foreground mb-3">
                  Showing {items.length} of {total} actors
                </p>
              )}
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead style={{ width: "30%" }}>Name</TableHead>
                    <TableHead style={{ width: "12%" }}>Country</TableHead>
                    <TableHead style={{ width: "14%" }}>Motivation</TableHead>
                    <TableHead style={{ width: "14%" }}>Sophistication</TableHead>
                    <TableHead style={{ width: "10%" }}>MITRE ID</TableHead>
                    <TableHead style={{ width: "10%" }}>First Seen</TableHead>
                    {isLead && (
                      <TableHead style={{ width: "10%" }}>
                        <span className="sr-only">Actions</span>
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((actor) => (
                    <TableRow key={actor.id} className="hover:bg-card/50">
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <Link
                            href={`/actors/${actor.id}`}
                            className="font-medium text-teal-400 hover:text-teal-300 hover:underline"
                          >
                            {actor.primary_name}
                          </Link>
                          {actor.aliases && actor.aliases.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {actor.aliases.slice(0, 4).map((alias) => (
                                <span
                                  key={alias}
                                  className="text-[12px] font-mono bg-card border border-border text-muted-foreground px-2 py-1 rounded"
                                >
                                  {alias}
                                </span>
                              ))}
                              {actor.aliases.length > 4 && (
                                <span className="text-[12px] text-muted-foreground">
                                  +{actor.aliases.length - 4} more
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>{countryDisplay(actor.country)}</TableCell>
                      <TableCell>{actor.motivation ?? "—"}</TableCell>
                      <TableCell>
                        <SophisticationBadge value={actor.sophistication} />
                      </TableCell>
                      <TableCell>
                        {actor.mitre_group_id ? (
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
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell>{formatFirstSeen(actor.first_seen)}</TableCell>
                      {isLead && (
                        <TableCell>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Link href={`/actors/${actor.id}`}>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  aria-label="Edit actor"
                                  className="h-7 w-7"
                                >
                                  <Pencil className="h-4 w-4" />
                                </Button>
                              </Link>
                            </TooltipTrigger>
                            <TooltipContent>Edit actor</TooltipContent>
                          </Tooltip>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              {nextCursor && (
                <div className="flex justify-center mt-4">
                  <Button
                    variant="outline"
                    onClick={handleLoadMore}
                    disabled={loadingMore}
                  >
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

        {/* Create Actor Dialog (Lead+ only) */}
        {isLead && (
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>Create Actor</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleCreate} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="actor-name">Primary Name *</Label>
                  <Input
                    id="actor-name"
                    placeholder="e.g. APT29"
                    value={createForm.primary_name}
                    onChange={(e) =>
                      setCreateForm((f) => ({ ...f, primary_name: e.target.value }))
                    }
                    required
                  />
                  {createError && (
                    <p className="text-destructive text-sm">{createError}</p>
                  )}
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="actor-aliases">Aliases (comma-separated)</Label>
                  <Input
                    id="actor-aliases"
                    placeholder="Cozy Bear, The Dukes, Office Monkeys"
                    value={createForm.aliases_raw}
                    onChange={(e) =>
                      setCreateForm((f) => ({ ...f, aliases_raw: e.target.value }))
                    }
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="actor-country">Country</Label>
                    <Input
                      id="actor-country"
                      placeholder="Russia"
                      value={createForm.country}
                      onChange={(e) =>
                        setCreateForm((f) => ({ ...f, country: e.target.value }))
                      }
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="actor-motivation">Motivation</Label>
                    <Input
                      id="actor-motivation"
                      placeholder="Espionage"
                      value={createForm.motivation}
                      onChange={(e) =>
                        setCreateForm((f) => ({ ...f, motivation: e.target.value }))
                      }
                    />
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="actor-sophistication">Sophistication</Label>
                  <Select
                    value={createForm.sophistication || "unknown"}
                    onValueChange={(v) =>
                      setCreateForm((f) => ({
                        ...f,
                        sophistication: v === "unknown" ? "" : v,
                      }))
                    }
                  >
                    <SelectTrigger id="actor-sophistication">
                      <SelectValue placeholder="Select…" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="unknown">Unknown</SelectItem>
                      {SOPHISTICATION_OPTIONS.filter((s) => s !== "unknown").map((s) => (
                        <SelectItem key={s} value={s}>
                          {s.charAt(0).toUpperCase() + s.slice(1)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="actor-profile">Profile Notes</Label>
                  <Textarea
                    id="actor-profile"
                    placeholder="Brief actor profile (Markdown supported)…"
                    value={createForm.profile_md}
                    onChange={(e) =>
                      setCreateForm((f) => ({ ...f, profile_md: e.target.value }))
                    }
                    style={{ minHeight: 80 }}
                  />
                </div>
                <DialogFooter>
                  <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>
                    Discard
                  </Button>
                  <Button
                    type="submit"
                    disabled={creating || createForm.primary_name.trim().length < 2}
                    className="bg-teal-600 hover:bg-teal-500 text-white"
                  >
                    {creating ? <Loader2 className="animate-spin h-4 w-4 mr-2" /> : null}
                    Create Actor
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
