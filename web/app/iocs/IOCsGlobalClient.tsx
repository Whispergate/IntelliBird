/**
 * IOCsGlobalClient - cross-project IOC search client component.
 * Adapted from web/app/projects/[id]/iocs/IOCsClient.tsx.
 * Key difference: no projectId prop; buildParams() omits projectId entirely.
 * Backend ACL (build_ioc_scope_predicate) handles cross-project scope.
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Loader2, Search } from "lucide-react";

import {
  listIOCs,
  type IOCRead,
  type IOCListParams,
} from "@/app/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";

import { TypeBadge, StatusPill, ConfidenceBadge, SourceBadge } from "@/app/projects/[id]/iocs/badges";
import { IOCDetailDrawer } from "@/app/projects/[id]/iocs/IOCDetailDrawer";

const PAGE_SIZE = 50;

const STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "expired", label: "Expired" },
  { value: "whitelisted", label: "Whitelisted" },
  { value: "all", label: "All statuses" },
];

const AGE_OPTIONS = [
  { value: "any", label: "Any" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last year" },
];

const TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "all", label: "All types" },
  { value: "ip", label: "ip" },
  { value: "ipv6", label: "ipv6" },
  { value: "domain", label: "domain" },
  { value: "url", label: "url" },
  { value: "email", label: "email" },
  { value: "sha256", label: "sha256" },
  { value: "sha1", label: "sha1" },
  { value: "md5", label: "md5" },
  { value: "filename", label: "filename" },
  { value: "mutex", label: "mutex" },
  { value: "registry_key", label: "registry_key" },
  { value: "btc", label: "btc" },
  { value: "eth", label: "eth" },
];

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

interface Props {
  initialRows: IOCRead[];
  initialQ?: string;
}

export function IOCsGlobalClient({ initialRows, initialQ = "" }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  // Filter state - initial from URL params (fallback to initialQ for q)
  const [typeFilter, setTypeFilter] = useState<string>(sp.get("type") ?? "all");
  const [statusFilter, setStatusFilter] = useState<string>(
    sp.get("status") ?? "active",
  );
  const [ageFilter, setAgeFilter] = useState<string>(sp.get("age") ?? "any");
  const [minConfidence, setMinConfidence] = useState<string>(
    sp.get("min_confidence") ?? "",
  );
  const [search, setSearch] = useState<string>(sp.get("q") ?? initialQ);
  const [debouncedSearch, setDebouncedSearch] = useState<string>(
    sp.get("q") ?? initialQ,
  );

  // Data state
  const [rows, setRows] = useState<IOCRead[]>(initialRows);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(initialRows.length >= PAGE_SIZE);
  const [error, setError] = useState<string | null>(null);
  const selectedIocId = sp.get("ioc");
  const selectedIoc = rows.find((r) => r.id === selectedIocId) ?? null;

  const isFirstRender = useRef(true);

  // Debounce search
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(t);
  }, [search]);

  // Sync URL params on filter change
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    const next = new URLSearchParams();
    if (typeFilter !== "all") next.set("type", typeFilter);
    if (statusFilter !== "active") next.set("status", statusFilter);
    if (ageFilter !== "any") next.set("age", ageFilter);
    if (minConfidence) next.set("min_confidence", minConfidence);
    if (debouncedSearch) next.set("q", debouncedSearch);
    if (selectedIocId) next.set("ioc", selectedIocId);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname);
  }, [
    typeFilter,
    statusFilter,
    ageFilter,
    minConfidence,
    debouncedSearch,
    selectedIocId,
    pathname,
    router,
  ]);

  const buildParams = useCallback(
    (cursor?: string): IOCListParams => {
      const params: IOCListParams = { limit: PAGE_SIZE };
      // projectId intentionally omitted → cross-project scope via build_ioc_scope_predicate
      if (typeFilter !== "all") params.type = [typeFilter];
      if (statusFilter !== "active") {
        if (statusFilter === "all") {
          params.include_expired = true;
        } else {
          params.status = statusFilter;
        }
      } else {
        params.status = "active";
      }
      if (ageFilter !== "any") params.age_days = Number(ageFilter);
      if (minConfidence) {
        const n = Number(minConfidence);
        if (isFinite(n)) params.min_confidence = n;
      }
      if (debouncedSearch) params.q = debouncedSearch;
      if (cursor) params.cursor = cursor;
      return params;
    },
    [typeFilter, statusFilter, ageFilter, minConfidence, debouncedSearch],
  );

  // Refetch on filter change (skip first render - initialRows already populated)
  const skipFetchRef = useRef(true);
  useEffect(() => {
    if (skipFetchRef.current) {
      skipFetchRef.current = false;
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    listIOCs(buildParams())
      .then((data) => {
        if (cancelled) return;
        setRows(data);
        setHasMore(data.length >= PAGE_SIZE);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        toast.error(`Could not load IOCs. ${msg}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [buildParams]);

  async function loadMore() {
    if (rows.length === 0) return;
    const last = rows[rows.length - 1];
    setLoadingMore(true);
    try {
      const more = await listIOCs(buildParams(last.id));
      setRows((r) => [...r, ...more]);
      setHasMore(more.length >= PAGE_SIZE);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Could not load IOCs. ${msg}`);
    } finally {
      setLoadingMore(false);
    }
  }

  async function refetch() {
    setLoading(true);
    try {
      const data = await listIOCs(buildParams());
      setRows(data);
      setHasMore(data.length >= PAGE_SIZE);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Could not load IOCs. ${msg}`);
    } finally {
      setLoading(false);
    }
  }

  function openDrawer(iocId: string) {
    const next = new URLSearchParams(sp.toString());
    next.set("ioc", iocId);
    router.push(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function closeDrawer() {
    const next = new URLSearchParams(sp.toString());
    next.delete("ioc");
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const anyFilterActive = useMemo(
    () =>
      typeFilter !== "all" ||
      statusFilter !== "active" ||
      ageFilter !== "any" ||
      minConfidence !== "" ||
      debouncedSearch !== "",
    [typeFilter, statusFilter, ageFilter, minConfidence, debouncedSearch],
  );

  function resetFilters() {
    setTypeFilter("all");
    setStatusFilter("active");
    setAgeFilter("any");
    setMinConfidence("");
    setSearch("");
  }

  const showEmptyNoIocs =
    !loading && rows.length === 0 && !anyFilterActive && !error;
  const showEmptyFiltered =
    !loading && rows.length === 0 && anyFilterActive && !error;

  return (
    <div className="space-y-6">
      {/* Header - Global IOC Search */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-semibold">Global IOC Search</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Search indicators across all projects you have access to.
          </p>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap p-3 rounded-md bg-card border border-border">
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="h-9 w-[140px]" aria-label="Type filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TYPE_OPTIONS.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-9 w-[150px]" aria-label="Status filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          type="number"
          min="0"
          max="1"
          step="0.05"
          value={minConfidence}
          onChange={(e) => setMinConfidence(e.target.value)}
          placeholder="Min confidence"
          className="h-9 w-32 font-mono text-[12px]"
          aria-label="Min confidence"
        />
        <Select value={ageFilter} onValueChange={setAgeFilter}>
          <SelectTrigger className="h-9 w-[150px]" aria-label="Age filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {AGE_OPTIONS.map((a) => (
              <SelectItem key={a.value} value={a.value}>
                {a.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search IOC value (e.g. 1.2.3.4, evil.com)"
            className="h-9 pl-8"
            aria-label="Search IOC"
          />
        </div>
        {anyFilterActive && (
          <Button size="sm" variant="ghost" onClick={resetFilters}>
            Reset filters
          </Button>
        )}
      </div>

      {/* Error */}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Empty: no IOCs */}
      {showEmptyNoIocs && (
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <h2 className="text-[22px] font-medium leading-[1.3]">
            No IOCs found.
          </h2>
          <p className="text-muted-foreground max-w-md leading-[1.7]">
            No indicators are available across your accessible projects yet.
          </p>
        </div>
      )}

      {/* Empty: filters returned zero */}
      {showEmptyFiltered && (
        <div className="flex flex-col items-center justify-center py-12 gap-3 text-center">
          <p className="text-muted-foreground leading-[1.7]">
            No IOCs match the current filters.
          </p>
          <Button size="sm" variant="ghost" onClick={resetFilters}>
            Reset filters
          </Button>
        </div>
      )}

      {/* Table */}
      {(rows.length > 0 || loading) && (
        <div className="rounded-md border border-border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[96px]">Type</TableHead>
                <TableHead className="max-w-[360px]">Value</TableHead>
                <TableHead className="w-[140px]">Confidence</TableHead>
                <TableHead className="w-[120px]">Status</TableHead>
                <TableHead className="w-[120px]">First seen</TableHead>
                <TableHead className="w-[120px]">Last seen</TableHead>
                <TableHead className="w-[120px]">Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading && rows.length === 0
                ? Array.from({ length: 6 }).map((_, i) => (
                    <TableRow key={`sk-${i}`}>
                      <TableCell colSpan={7}>
                        <div className="h-[28px] bg-card/50 animate-pulse rounded-sm" />
                      </TableCell>
                    </TableRow>
                  ))
                : rows.map((ioc) => (
                    <TableRow
                      key={ioc.id}
                      className={
                        selectedIocId === ioc.id ? "bg-card/60" : undefined
                      }
                    >
                      <TableCell>
                        <TypeBadge type={ioc.type} />
                      </TableCell>
                      <TableCell className="max-w-[360px]">
                        <button
                          type="button"
                          onClick={() => openDrawer(ioc.id)}
                          className="font-mono text-[12px] text-foreground truncate block text-left hover:underline decoration-[var(--brand-signal)] underline-offset-2"
                          title={ioc.value}
                        >
                          {ioc.value}
                        </button>
                      </TableCell>
                      <TableCell>
                        <ConfidenceBadge confidence={ioc.confidence} />
                      </TableCell>
                      <TableCell>
                        <StatusPill status={ioc.status} />
                      </TableCell>
                      <TableCell className="text-[12px] text-muted-foreground">
                        {fmtDate(ioc.first_seen)}
                      </TableCell>
                      <TableCell className="text-[12px] text-muted-foreground">
                        {fmtDate(ioc.last_seen)}
                      </TableCell>
                      <TableCell>
                        <SourceBadge source={ioc.source} />
                      </TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Load more */}
      {hasMore && rows.length > 0 && (
        <div className="flex justify-center mt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void loadMore()}
            disabled={loadingMore}
          >
            {loadingMore ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                Loading…
              </>
            ) : (
              "Load more"
            )}
          </Button>
        </div>
      )}

      {/* Detail drawer - pass ioc.project_id for cross-project context */}
      {selectedIocId && (
        <IOCDetailDrawer
          iocId={selectedIocId}
          projectId={selectedIoc?.project_id ?? ""}
          onClose={closeDrawer}
          onMutate={refetch}
        />
      )}
    </div>
  );
}
