"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { toast } from "sonner";

import {
  listEvents,
  getPreset,
  type EventItem,
  type TlpName,
} from "@/app/api-client";
import { useRole } from "@/app/lib/role-context";
import { TypeBadge } from "@/app/sources/components/TypeBadge";
import { formatRelativeTime } from "@/app/sources/lib/relativeTime";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// TLP badge color map per UI-SPEC EventsList specification.
const TLP_STYLE: Record<string, { bg: string; fg: string; border: string }> = {
  clear: { bg: "rgba(136,135,128,0.15)", fg: "#888780", border: "#888780" },
  green: { bg: "rgba(29,158,117,0.15)", fg: "#9FE1CB", border: "#1D9E75" },
  amber: { bg: "rgba(239,159,39,0.15)", fg: "#EF9F27", border: "#EF9F27" },
  "amber+strict": { bg: "rgba(239,159,39,0.25)", fg: "#EF9F27", border: "#EF9F27" },
  red: { bg: "rgba(220,38,38,0.15)", fg: "#fca5a5", border: "#dc2626" },
};

const NULL_TLP_STYLE = { bg: "rgba(136,135,128,0.10)", fg: "#888780", border: "#888780" };

function TlpBadge({ tlp }: { tlp: TlpName | null }) {
  const style = tlp ? (TLP_STYLE[tlp] ?? NULL_TLP_STYLE) : NULL_TLP_STYLE;
  return (
    <Badge
      variant="outline"
      className="brand-caption"
      style={{
        backgroundColor: style.bg,
        color: style.fg,
        borderColor: style.border,
      }}
    >
      {tlp ?? "\u2014"}
    </Badge>
  );
}

type Props = {
  /** When provided by a parent coordinator (e.g. DashboardClient), skip self-fetch. */
  items?: EventItem[];
  /** Loading state from parent coordinator. Only used when `items` is provided. */
  loading?: boolean;
};

export function DashboardEventsList(props: Props = {}) {
  const externalItems = props.items;
  const role = useRole();
  const router = useRouter();
  const pathname = usePathname();
  const [internalItems, setInternalItems] = useState<EventItem[] | null>(
    externalItems !== undefined ? (externalItems as EventItem[]) : null,
  );
  const [internalLoading, setInternalLoading] = useState(
    externalItems !== undefined ? !!props.loading : true,
  );

  const items = externalItems !== undefined ? externalItems : internalItems;
  const loading = externalItems !== undefined ? !!props.loading : internalLoading;

  useEffect(() => {
    if (externalItems !== undefined) return; // parent owns fetching
    let cancelled = false;
    const presetName = `default-${role}`;
    (async () => {
      try {
        // Two-step pattern: fetch preset then merge into events query.
        // The events API (/api/events) does NOT accept a preset_name param (confirmed by
        // inspecting backend/app/routers/events.py — no preset_name in Query declaration).
        // This two-step approach is safe and avoids server-side coupling.
        let presetQuery: Record<string, unknown> = {};
        try {
          const preset = await getPreset(presetName);
          presetQuery = preset.query_params ?? {};
        } catch {
          // Preset not yet seeded — proceed with empty query; list will still render.
        }
        const res = await listEvents(
          { ...(presetQuery as object), limit: 25 },
          role,
        );
        if (!cancelled) {
          setInternalItems(res.items);
          setInternalLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          toast.error("Failed to load events.");
          setInternalItems([]);
          setInternalLoading(false);
        }
        // eslint-disable-next-line no-console
        console.warn("[DashboardEventsList] listEvents failed", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [role, externalItems]);

  function openEvent(id: string) {
    router.replace(`${pathname}?event=${encodeURIComponent(id)}`);
  }

  if (loading) {
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead style={{ width: 80 }}>Type</TableHead>
            <TableHead style={{ width: 72 }}>TLP</TableHead>
            <TableHead style={{ width: 88 }}>ATT&amp;CK</TableHead>
            <TableHead style={{ width: 120 }}>Source</TableHead>
            <TableHead style={{ width: 100 }}>Observed</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: 5 }).map((_, i) => (
            <TableRow key={i} data-testid="events-skeleton-row">
              <TableCell colSpan={6}>
                <div className="animate-pulse bg-muted rounded h-4 w-full" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div
        data-testid="events-empty"
        className="flex flex-col items-center justify-center py-12 gap-2"
      >
        <h2 className="brand-heading text-foreground">No events yet.</h2>
        <p className="text-muted-foreground" style={{ fontSize: 16 }}>
          Register sources and wait for the first poll, or check your filter preset.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <caption className="sr-only">{role} dashboard events</caption>
      <TableHeader>
        <TableRow>
          <TableHead>Title</TableHead>
          <TableHead style={{ width: 80 }}>Type</TableHead>
          <TableHead style={{ width: 72 }}>TLP</TableHead>
          <TableHead style={{ width: 88 }}>ATT&amp;CK</TableHead>
          <TableHead style={{ width: 120 }}>Source</TableHead>
          <TableHead style={{ width: 100 }}>Observed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((evt) => (
          <TableRow
            key={evt.id}
            data-testid="events-row"
            data-event-id={evt.id}
            tabIndex={0}
            onClick={() => openEvent(evt.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openEvent(evt.id);
              }
            }}
            className="cursor-pointer hover:bg-card h-12"
          >
            <TableCell
              className="truncate"
              style={{ maxWidth: "60ch" }}
              title={evt.title ?? undefined}
            >
              {evt.title ?? "Untitled event"}
            </TableCell>
            <TableCell>
              {evt.source_type ? <TypeBadge feed_type={evt.source_type} /> : null}
            </TableCell>
            <TableCell>
              <TlpBadge tlp={evt.tlp} />
            </TableCell>
            <TableCell>
              <span className="brand-caption text-muted-foreground">
                {evt.attack_techniques.length > 0
                  ? `${evt.attack_techniques.length} TTPs`
                  : "\u2014"}
              </span>
            </TableCell>
            <TableCell className="truncate" style={{ maxWidth: 120 }}>
              {evt.source_name ?? "\u2014"}
            </TableCell>
            <TableCell>{formatRelativeTime(evt.observed_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
