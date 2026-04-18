"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";

import type { Source } from "@/app/api-client";
import { updateSource } from "@/app/api-client";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatusBadge } from "./StatusBadge";
import { TypeBadge } from "./TypeBadge";
import { formatInterval, formatRelativeTime } from "../lib/relativeTime";

type SortKey = "name" | "feed_type" | "last_polled_at" | "effective_status";
type SortDir = "asc" | "desc";

type Props = {
  initialSources: Source[];
  onAdd: () => void;
  onEdit: (source: Source) => void;
  onDelete: (source: Source) => void;
};

export function SourceTable({ initialSources, onAdd, onEdit, onDelete }: Props) {
  const [sources, setSources] = useState<Source[]>(initialSources);
  const [sortKey, setSortKey] = useState<SortKey>("last_polled_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = [...sources].sort((a, b) => {
    const av = (a as Record<string, unknown>)[sortKey];
    const bv = (b as Record<string, unknown>)[sortKey];
    // NULLs last regardless of direction
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (av < bv) return sortDir === "asc" ? -1 : 1;
    if (av > bv) return sortDir === "asc" ? 1 : -1;
    return 0;
  });

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  async function onToggleEnabled(src: Source, next: boolean) {
    // Optimistic update
    setSources((prev) =>
      prev.map((s) => (s.id === src.id ? { ...s, enabled: next } : s)),
    );
    try {
      await updateSource(src.id, { enabled: next });
    } catch {
      // Revert + toast
      setSources((prev) =>
        prev.map((s) => (s.id === src.id ? { ...s, enabled: !next } : s)),
      );
      toast.error("Could not update source. Reverted.");
    }
  }

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-2">
        <h2 className="text-xl font-semibold leading-tight">No sources yet.</h2>
        <p className="text-sm font-normal leading-normal text-muted-foreground">
          Add your first feed to start ingesting threat intelligence.
        </p>
        <div className="mt-2">
          <Button onClick={onAdd}>Add Source</Button>
        </div>
      </div>
    );
  }

  const headerClick = (key: SortKey) => () => toggleSort(key);
  const chevron = (key: SortKey) =>
    sortKey === key ? (
      sortDir === "asc" ? (
        <ChevronUp className="inline h-3 w-3 ml-1 text-primary" />
      ) : (
        <ChevronDown className="inline h-3 w-3 ml-1 text-primary" />
      )
    ) : null;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="cursor-pointer" onClick={headerClick("name")}>
            Name{chevron("name")}
          </TableHead>
          <TableHead className="cursor-pointer" onClick={headerClick("feed_type")}>
            Type{chevron("feed_type")}
          </TableHead>
          <TableHead>URL</TableHead>
          <TableHead>Interval</TableHead>
          <TableHead className="cursor-pointer" onClick={headerClick("last_polled_at")}>
            Last Polled{chevron("last_polled_at")}
          </TableHead>
          <TableHead className="cursor-pointer" onClick={headerClick("effective_status")}>
            Status{chevron("effective_status")}
          </TableHead>
          <TableHead>Enabled</TableHead>
          <TableHead>Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((src) => (
          <TableRow
            key={src.id}
            className={`${src.enabled ? "" : "opacity-60"} h-12 cursor-pointer hover:bg-card`}
            onClick={(e) => {
              // Avoid firing edit when clicking Switch or Actions
              const target = e.target as HTMLElement;
              if (target.closest('[data-no-row-click="true"]')) return;
              onEdit(src);
            }}
          >
            <TableCell className="truncate max-w-[200px]">{src.name}</TableCell>
            <TableCell>
              <TypeBadge feed_type={src.feed_type} />
            </TableCell>
            <TableCell className="brand-mono truncate max-w-[240px] text-muted-foreground">
              {src.url}
            </TableCell>
            <TableCell>{formatInterval(src.poll_interval_sec)}</TableCell>
            <TableCell>
              {formatRelativeTime(src.last_polled_at)}
              {src.consecutive_failures > 0 ? ` · ${src.consecutive_failures} fails` : ""}
            </TableCell>
            <TableCell>
              <StatusBadge
                last_status={src.last_status}
                effective_status={src.effective_status}
                last_polled_at={src.last_polled_at}
                consecutive_failures={src.consecutive_failures}
              />
            </TableCell>
            <TableCell data-no-row-click="true" className="min-h-[44px]">
              <Switch
                checked={src.enabled}
                onCheckedChange={(next) => onToggleEnabled(src, next)}
                aria-label={src.enabled ? `Disable ${src.name}` : `Enable ${src.name}`}
              />
            </TableCell>
            <TableCell data-no-row-click="true" className="min-h-[44px]">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Actions for ${src.name}`}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => onEdit(src)}>
                    Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="text-destructive"
                    onClick={() => onDelete(src)}
                    aria-label={`Delete source ${src.name}`}
                  >
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
