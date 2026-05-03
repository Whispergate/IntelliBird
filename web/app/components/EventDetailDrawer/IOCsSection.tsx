"use client";

/**
 * IOCsSection — Phase 22 Plan 06 (UI-SPEC §Surface 5).
 *
 * Renders inside EventDetailDrawer. Sources data from the concrete
 * `GET /api/events/{id}/iocs` endpoint added in Plan 22-03. Compact chip-row
 * list — clicking a chip deep-links to /projects/{project_id}/iocs?ioc=<uuid>.
 */

import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";

import { listEventIOCs, type IOCRead } from "@/app/api-client";
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

export function IOCsSection({ eventId, projectId }: Props) {
  const [iocs, setIocs] = useState<IOCRead[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    listEventIOCs(eventId)
      .then((data) => {
        if (!cancelled) setIocs(data);
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
            const inner = (
              <>
                <TypeBadge type={ioc.type} />
                <span className="font-mono text-[12px] text-foreground truncate flex-1">
                  {ioc.value}
                </span>
                <ConfidenceBadge confidence={ioc.confidence} compact />
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
