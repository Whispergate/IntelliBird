"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";

import type { Webhook } from "@/app/api-client";
import { updateWebhook } from "@/app/api-client";
import { Badge } from "@/components/ui/badge";
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
import { WebhookStatusBadge } from "./WebhookStatusBadge";
import { WebhookTypeBadge } from "./WebhookTypeBadge";
import { formatRelativeTime } from "../lib/relativeTime";

type SortKey = "name" | "destination_type" | "last_delivery_at" | "consecutive_failures";
type SortDir = "asc" | "desc";

type Props = {
  initialWebhooks: Webhook[];
  onAdd: () => void;
  onEdit: (webhook: Webhook) => void;
  onDelete: (webhook: Webhook) => void;
};

export function WebhookTable({ initialWebhooks, onAdd, onEdit, onDelete }: Props) {
  const [webhooks, setWebhooks] = useState<Webhook[]>(initialWebhooks);
  const [sortKey, setSortKey] = useState<SortKey>("last_delivery_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = [...webhooks].sort((a, b) => {
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

  async function onToggleEnabled(wh: Webhook, next: boolean) {
    // Optimistic update
    setWebhooks((prev) =>
      prev.map((w) => (w.id === wh.id ? { ...w, enabled: next } : w)),
    );
    try {
      await updateWebhook(wh.id, { enabled: next });
    } catch {
      // Revert + toast
      setWebhooks((prev) =>
        prev.map((w) => (w.id === wh.id ? { ...w, enabled: !next } : w)),
      );
      toast.error("Could not update webhook. Reverted.");
    }
  }

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-2">
        <h2 className="text-xl font-semibold leading-tight">No webhooks yet.</h2>
        <p className="text-sm font-normal leading-normal text-muted-foreground">
          Add your first destination to start receiving alerts.
        </p>
        <div className="mt-2">
          <Button onClick={onAdd}>Add Webhook</Button>
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
          <TableHead className="cursor-pointer" onClick={headerClick("destination_type")}>
            Type{chevron("destination_type")}
          </TableHead>
          <TableHead>URL</TableHead>
          <TableHead>Bound Presets</TableHead>
          <TableHead className="cursor-pointer" onClick={headerClick("last_delivery_at")}>
            Status{chevron("last_delivery_at")}
          </TableHead>
          <TableHead>Enabled</TableHead>
          <TableHead>Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((wh) => (
          <TableRow
            key={wh.id}
            className={`${wh.enabled ? "" : "opacity-60"} h-12 cursor-pointer hover:bg-card`}
            onClick={(e) => {
              // Avoid firing edit when clicking Switch or Actions
              const target = e.target as HTMLElement;
              if (target.closest('[data-no-row-click="true"]')) return;
              onEdit(wh);
            }}
          >
            <TableCell className="truncate max-w-[200px]">{wh.name}</TableCell>
            <TableCell>
              <WebhookTypeBadge destination_type={wh.destination_type} />
            </TableCell>
            <TableCell className="brand-mono truncate max-w-[240px] text-muted-foreground">
              {wh.url}
            </TableCell>
            <TableCell>
              {wh.bound_preset_names.length === 0 ? (
                <span className="text-xs text-muted-foreground">No presets bound</span>
              ) : (
                wh.bound_preset_names.map((n) => (
                  <Badge key={n} variant="outline" className="mr-1 text-xs">
                    {n}
                  </Badge>
                ))
              )}
            </TableCell>
            <TableCell>
              <div className="flex flex-col gap-1 items-start">
                <WebhookStatusBadge webhook={wh} />
                <span className="text-xs text-muted-foreground">
                  {formatRelativeTime(wh.last_delivery_at)}
                  {wh.consecutive_failures > 0 ? ` · ${wh.consecutive_failures} fails` : ""}
                </span>
              </div>
            </TableCell>
            <TableCell data-no-row-click="true" className="min-h-[44px]">
              <Switch
                checked={wh.enabled}
                onCheckedChange={(next) => onToggleEnabled(wh, next)}
                aria-label={wh.enabled ? `Disable ${wh.name}` : `Enable ${wh.name}`}
              />
            </TableCell>
            <TableCell data-no-row-click="true" className="min-h-[44px]">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Actions for ${wh.name}`}
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => onEdit(wh)}>
                    Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="text-destructive"
                    onClick={() => onDelete(wh)}
                    aria-label={`Delete webhook ${wh.name}`}
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
