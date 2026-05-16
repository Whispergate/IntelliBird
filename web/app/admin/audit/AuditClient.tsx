"use client";

import React, { useState, useEffect, useCallback } from "react";
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
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";

import { listAuditLog, type AuditLogRead, type AuditLogListResponse } from "@/app/api-client";
import { ActionBadge } from "./badges";
import { AuditDiffViewer } from "./AuditDiffViewer";

// ── Date range helpers ──────────────────────────────────────────────────────

type DateRange = "24h" | "7d" | "30d" | "90d" | "custom";

function dateRangeToParams(range: DateRange): { from_dt: string; to_dt: string } {
  const now = new Date();
  const to_dt = now.toISOString();
  const msMap: Record<Exclude<DateRange, "custom">, number> = {
    "24h": 24 * 60 * 60 * 1000,
    "7d":  7  * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
    "90d": 90 * 24 * 60 * 60 * 1000,
  };
  const ms = msMap[range as Exclude<DateRange, "custom">];
  const from_dt = new Date(now.getTime() - ms).toISOString();
  return { from_dt, to_dt };
}

// ── Timestamp formatter ─────────────────────────────────────────────────────

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

// ── Resource type options ───────────────────────────────────────────────────

const RESOURCE_TYPE_OPTIONS = [
  "sources",
  "projects",
  "actors",
  "campaigns",
  "iocs",
  "enrichment_providers",
  "ai_suggestions",
  "webhooks",
];

const ACTION_OPTIONS = ["create", "update", "delete", "approve", "reject"];

// ── Props ───────────────────────────────────────────────────────────────────

interface AuditClientProps {
  initialData: AuditLogListResponse | null;
}

// ── Component ───────────────────────────────────────────────────────────────

export default function AuditClient({ initialData }: AuditClientProps) {
  const [items, setItems] = useState<AuditLogRead[]>(initialData?.items ?? []);
  const [nextCursor, setNextCursor] = useState<string | null>(initialData?.next_cursor ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  // Filter state
  const [userSub, setUserSub] = useState("");
  const [resourceType, setResourceType] = useState("all");
  const [action, setAction] = useState("all");
  const [dateRange, setDateRange] = useState<DateRange>("30d");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  // Compute unique user_sub values from loaded items for the User select
  const uniqueUsers = Array.from(
    new Set(items.map((i) => i.user_sub).filter((s): s is string => s !== null))
  ).sort();

  // Is any filter non-default?
  const hasNonDefaultFilter =
    userSub !== "" ||
    resourceType !== "all" ||
    action !== "all" ||
    dateRange !== "30d";

  // Build query params from current filter state
  const buildParams = useCallback(
    (cursor?: string) => {
      const params: Parameters<typeof listAuditLog>[0] = { limit: 100 };
      if (userSub) params.user_sub = userSub;
      if (resourceType !== "all") params.resource_type = resourceType;
      if (action !== "all") params.action = action;

      if (dateRange === "custom") {
        if (customFrom) params.from_dt = new Date(customFrom).toISOString();
        if (customTo)   params.to_dt   = new Date(customTo).toISOString();
      } else {
        const { from_dt, to_dt } = dateRangeToParams(dateRange);
        params.from_dt = from_dt;
        params.to_dt   = to_dt;
      }

      if (cursor) params.cursor = cursor;
      return params;
    },
    [userSub, resourceType, action, dateRange, customFrom, customTo]
  );

  // Load from top (reset cursor)
  const loadFresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    setExpandedRowId(null);
    try {
      const data = await listAuditLog(buildParams());
      setItems(data.items);
      setNextCursor(data.next_cursor);
    } catch {
      setError("Could not load audit log. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  // Load older items (append)
  const loadOlder = useCallback(async () => {
    if (!nextCursor) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listAuditLog(buildParams(nextCursor));
      setItems((prev) => [...prev, ...data.items]);
      setNextCursor(data.next_cursor);
    } catch {
      setError("Could not load audit log. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }, [buildParams, nextCursor]);

  // Reload when filters change
  useEffect(() => {
    if (!initialData) {
      loadFresh();
    }
    // Only run on filter changes after initial mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userSub, resourceType, action, dateRange, customFrom, customTo]);

  const clearFilters = () => {
    setUserSub("");
    setResourceType("all");
    setAction("all");
    setDateRange("30d");
    setCustomFrom("");
    setCustomTo("");
  };

  // Copy resource ID to clipboard
  const copyToClipboard = (text: string) => {
    if (typeof navigator !== "undefined") {
      navigator.clipboard.writeText(text).catch(() => {});
    }
  };

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 items-center">
        {/* User filter */}
        <Select
          value={userSub === "" ? "all" : userSub}
          onValueChange={(v) => setUserSub(v === "all" ? "" : v)}
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="All users" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All users</SelectItem>
            {uniqueUsers.map((u) => (
              <SelectItem key={u} value={u}>
                {u.length > 24 ? u.slice(0, 24) + "…" : u}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Resource type filter */}
        <Select value={resourceType} onValueChange={setResourceType}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="All resource types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All resource types</SelectItem>
            {RESOURCE_TYPE_OPTIONS.map((rt) => (
              <SelectItem key={rt} value={rt}>
                {rt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Action filter */}
        <Select value={action} onValueChange={setAction}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="All actions" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All actions</SelectItem>
            {ACTION_OPTIONS.map((a) => (
              <SelectItem key={a} value={a}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Date range */}
        <Select value={dateRange} onValueChange={(v) => setDateRange(v as DateRange)}>
          <SelectTrigger className="w-[160px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="24h">Last 24h</SelectItem>
            <SelectItem value="7d">Last 7d</SelectItem>
            <SelectItem value="30d">Last 30d</SelectItem>
            <SelectItem value="90d">Last 90d</SelectItem>
            <SelectItem value="custom">Custom</SelectItem>
          </SelectContent>
        </Select>

        {/* Custom date inputs */}
        {dateRange === "custom" && (
          <>
            <Input
              type="datetime-local"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
              className="w-[200px]"
              aria-label="From date"
            />
            <Input
              type="datetime-local"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
              className="w-[200px]"
              aria-label="To date"
            />
          </>
        )}

        {/* Clear filters */}
        {hasNonDefaultFilter && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            Clear filters
          </Button>
        )}

        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
      </div>

      {/* Row count */}
      {!loading && !error && (
        <p className="text-sm text-muted-foreground">Showing {items.length} rows</p>
      )}

      {/* Error state */}
      {error && (
        <div className="flex items-center justify-center py-12">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      {/* Table */}
      {!error && (
        <div className="rounded-md border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead style={{ width: "16%" }}>Timestamp</TableHead>
                <TableHead style={{ width: "16%" }}>User</TableHead>
                <TableHead style={{ width: "8%" }}>Action</TableHead>
                <TableHead style={{ width: "14%" }}>Resource Type</TableHead>
                <TableHead style={{ width: "16%" }}>Resource ID</TableHead>
                <TableHead style={{ width: "12%" }}>Project</TableHead>
                <TableHead style={{ width: "8%" }}>Diff</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!loading && items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                    No audit events match the current filters.
                  </TableCell>
                </TableRow>
              )}
              {items.map((row) => (
                <React.Fragment key={row.id}>
                  <TableRow>
                    {/* Timestamp */}
                    <TableCell>
                      <span className="font-mono text-[13px]">{formatTimestamp(row.time)}</span>
                    </TableCell>

                    {/* User */}
                    <TableCell>
                      {row.user_sub ? (
                        <span className="font-mono text-[12px] bg-muted px-1.5 py-0.5 rounded">
                          {row.user_sub.length > 24 ? row.user_sub.slice(0, 24) + "…" : row.user_sub}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>

                    {/* Action */}
                    <TableCell>
                      <ActionBadge action={row.action} />
                    </TableCell>

                    {/* Resource Type */}
                    <TableCell>
                      <span className="text-[12px] font-medium uppercase tracking-wide">
                        {row.resource_type}
                      </span>
                    </TableCell>

                    {/* Resource ID */}
                    <TableCell>
                      {row.resource_id ? (
                        <button
                          onClick={() => copyToClipboard(row.resource_id!)}
                          title="Click to copy"
                          className="font-mono text-[12px] bg-muted px-1.5 py-0.5 rounded hover:bg-muted/70 transition-colors cursor-pointer"
                        >
                          {row.resource_id.length > 16
                            ? row.resource_id.slice(0, 16) + "…"
                            : row.resource_id}
                        </button>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>

                    {/* Project */}
                    <TableCell>
                      <span className="text-sm">
                        {row.project_id ?? "Global"}
                      </span>
                    </TableCell>

                    {/* Diff */}
                    <TableCell>
                      {row.before_jsonb !== null || row.after_jsonb !== null ? (
                        <button
                          onClick={() =>
                            setExpandedRowId(expandedRowId === row.id ? null : row.id)
                          }
                          className="text-[12px] text-primary hover:underline"
                        >
                          {expandedRowId === row.id ? "Hide diff" : "View diff"}
                        </button>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>

                  {/* Inline diff viewer */}
                  {expandedRowId === row.id && (
                    <TableRow>
                      <TableCell colSpan={7} className="p-0">
                        <AuditDiffViewer
                          before={row.before_jsonb}
                          after={row.after_jsonb}
                          onCollapse={() => setExpandedRowId(null)}
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </React.Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {!error && (
        <div className="flex gap-3 items-center justify-end">
          <Button
            variant="outline"
            size="sm"
            onClick={loadFresh}
            disabled={loading}
          >
            Newer
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={loadOlder}
            disabled={loading || !nextCursor}
          >
            Older
          </Button>
        </div>
      )}
    </div>
  );
}
