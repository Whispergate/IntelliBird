"use client";

/**
 * IOCsSection — Phase 22 Plan 06 (UI-SPEC §Surface 5).
 *
 * Renders inside EventDetailDrawer. Sources data from the concrete
 * `GET /api/events/{id}/iocs` endpoint added in Plan 22-03. Compact chip-row
 * list — clicking a chip deep-links to /projects/{project_id}/iocs?ioc=<uuid>.
 *
 * Phase 23 ENRICH-04: fetch enrichments for first 5 IOCs; render unified
 * verdict badge beside ConfidenceBadge when verdict is non-unknown.
 */

import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";

import {
  listEventIOCs,
  getIOCEnrichments,
  type IOCRead,
  type IOCEnrichmentRead,
} from "@/app/api-client";
import { TypeBadge, ConfidenceBadge } from "@/app/projects/[id]/iocs/badges";

interface Props {
  eventId: string;
  /**
   * Optional — when provided, chip click navigates to
   * `/projects/{projectId}/iocs?ioc=<uuid>`. Otherwise click is a no-op
   * (event drawer may render in a context without project context).
   */
  projectId?: string;
}

// Severity rank for worst-case aggregation
const VERDICT_RANK: Record<string, number> = {
  malicious: 3,
  suspicious: 2,
  unknown: 1,
  clean: 0,
};

function unifiedVerdict(rows: IOCEnrichmentRead[]): string {
  if (rows.length === 0) return "unknown";
  let worst = "clean";
  for (const r of rows) {
    if ((VERDICT_RANK[r.verdict] ?? 0) > (VERDICT_RANK[worst] ?? 0)) {
      worst = r.verdict;
    }
  }
  return worst;
}

function VerdictPill({ verdict }: { verdict: string }) {
  const colour =
    ({
      malicious: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
      suspicious:
        "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
      clean:
        "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300",
      unknown: "bg-muted text-muted-foreground",
    } as Record<string, string>)[verdict] ?? "bg-muted text-muted-foreground";
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colour}`}>
      {verdict}
    </span>
  );
}

export function IOCsSection({ eventId, projectId }: Props) {
  const [iocs, setIocs] = useState<IOCRead[] | null>(null);
  const [enrichmentMap, setEnrichmentMap] = useState<
    Record<string, IOCEnrichmentRead[]>
  >({});

  useEffect(() => {
    let cancelled = false;
    listEventIOCs(eventId)
      .then(async (data) => {
        if (cancelled) return;
        setIocs(data);
        // Fetch enrichments for first 5 IOCs (quota-burn guard)
        const map: Record<string, IOCEnrichmentRead[]> = {};
        await Promise.allSettled(
          data.slice(0, 5).map(async (ioc) => {
            try {
              map[ioc.id] = await getIOCEnrichments(ioc.id);
            } catch {
              // Silently skip — enrichment section is additive
            }
          }),
        );
        if (!cancelled) setEnrichmentMap(map);
      })
      .catch(() => {
        if (!cancelled) setIocs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [eventId]);

  if (iocs === null) {
    return (
      <section className="p-4 border-b" data-testid="drawer-section-iocs">
        <p className="brand-caption text-muted-foreground mb-2">IOCS</p>
        <div className="flex flex-col gap-1">
          <div className="h-6 bg-muted rounded animate-pulse" />
          <div className="h-6 bg-muted rounded animate-pulse" />
        </div>
      </section>
    );
  }

  return (
    <section className="p-4 border-b" data-testid="drawer-section-iocs">
      <h3 className="brand-caption text-muted-foreground uppercase mb-3">
        IOCs ({iocs.length})
      </h3>
      {iocs.length === 0 ? (
        <p className="text-[12px] text-muted-foreground py-2">
          No atomic indicators extracted from this event.
        </p>
      ) : (
        <ul className="flex flex-col">
          {iocs.map((ioc) => {
            const targetProject = projectId ?? ioc.project_id;
            const href =
              targetProject !== null && targetProject !== undefined
                ? `/projects/${targetProject}/iocs?ioc=${ioc.id}`
                : null;
            const iocVerdict = unifiedVerdict(enrichmentMap[ioc.id] ?? []);
            const inner = (
              <>
                <TypeBadge type={ioc.type} />
                <span className="font-mono text-[12px] text-foreground truncate flex-1">
                  {ioc.value}
                </span>
                <ConfidenceBadge confidence={ioc.confidence} compact />
                {iocVerdict !== "unknown" && (
                  <VerdictPill verdict={iocVerdict} />
                )}
                <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
              </>
            );
            return (
              <li key={ioc.id}>
                {href ? (
                  <a
                    href={href}
                    className="w-full flex items-center gap-2 py-1.5 px-2 rounded-sm hover:bg-card/60 text-left transition-colors"
                  >
                    {inner}
                  </a>
                ) : (
                  <div className="w-full flex items-center gap-2 py-1.5 px-2 rounded-sm">
                    {inner}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
