"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { ExternalLink } from "lucide-react";

import {
  getEvent,
  type EventDetail,
  type TlpName,
} from "@/app/api-client";
import { useRole } from "@/app/lib/role-context";
import { TypeBadge } from "@/app/sources/components/TypeBadge";
import { formatRelativeTime } from "@/app/sources/lib/relativeTime";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
} from "@/components/ui/sheet";
import { TagEditor } from "./TagEditor";
import { DrawerNav } from "./DrawerNav";
import { AttackGraph } from "./AttackGraph";
import { TierBadge } from "./TierBadge";
import { AISummarySection } from "./AISummarySection";
import { IOCsSection } from "./EventDetailDrawer/IOCsSection";
import { SandboxReportSection } from "./EventDetailDrawer/SandboxReportSection";
import { classifyTier, currentScore } from "@/lib/scoring";

// ---------------------------------------------------------------------------
// TLP badge (inline — no separate file required for a single-use primitive)
// ---------------------------------------------------------------------------

const TLP_STYLE: Record<string, { bg: string; fg: string; border: string }> = {
  clear: { bg: "rgba(136,135,128,0.15)", fg: "#888780", border: "#888780" },
  green: { bg: "rgba(29,158,117,0.15)", fg: "#9FE1CB", border: "#1D9E75" },
  amber: { bg: "rgba(239,159,39,0.15)", fg: "#EF9F27", border: "#EF9F27" },
  "amber+strict": {
    bg: "rgba(239,159,39,0.25)",
    fg: "#EF9F27",
    border: "#EF9F27",
  },
  red: { bg: "rgba(220,38,38,0.15)", fg: "#fca5a5", border: "#dc2626" },
};

const NULL_TLP_STYLE = {
  bg: "rgba(136,135,128,0.10)",
  fg: "#888780",
  border: "#888780",
};

const TECH_CHIP_STYLE = {
  backgroundColor: "rgba(159, 225, 203, 0.12)",
  color: "#9FE1CB",
  borderColor: "#0F6E56",
};

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
      {tlp ?? "—"}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// EventDetailDrawer
// ---------------------------------------------------------------------------

type EventDetailDrawerProps = {
  prevEventId?: string | null;
  nextEventId?: string | null;
  onNavigate?: (id: string) => void;
  currentIndex?: number;
  totalCount?: number;
};

export function EventDetailDrawer({
  prevEventId,
  nextEventId,
  onNavigate,
  currentIndex = 0,
  totalCount = 0,
}: EventDetailDrawerProps = {}) {
  const role = useRole();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedEventId = searchParams.get("event");
  // Extract project ID from /projects/[uuid]/... URL patterns
  const projectIdMatch = pathname?.match(/\/projects\/([0-9a-f-]{36})/i);
  const drawerProjectId = projectIdMatch ? projectIdMatch[1] : null;

  const [event, setEvent] = useState<EventDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedEventId) {
      setEvent(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getEvent(selectedEventId, role)
      .then((data) => {
        if (!cancelled) {
          setEvent(data);
          setLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
          toast.error("Failed to load event. Please try again.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedEventId, role]);

  // Keyboard navigation — ArrowLeft / ArrowRight (guarded: skip if focus inside input/textarea)
  useEffect(() => {
    if (!selectedEventId) return;
    function handler(e: KeyboardEvent) {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "ArrowLeft" && prevEventId && onNavigate) {
        e.preventDefault();
        onNavigate(prevEventId);
      } else if (e.key === "ArrowRight" && nextEventId && onNavigate) {
        e.preventDefault();
        onNavigate(nextEventId);
      }
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [selectedEventId, prevEventId, nextEventId, onNavigate]);

  function closeDrawer() {
    router.replace(pathname);
  }

  const showNav = totalCount > 0 && onNavigate != null;

  return (
    <Sheet
      open={!!selectedEventId}
      onOpenChange={(open) => {
        if (!open) closeDrawer();
      }}
    >
      <SheetContent
        side="right"
        className="w-[480px] sm:max-w-[480px] overflow-y-auto p-0"
        data-testid="event-detail-drawer"
      >
        {/* Section 1 — Header (sticky)*/}
        <SheetHeader
          className="p-4 border-b sticky top-0 z-10"
          style={{ background: "hsl(var(--card))" }}
        >
          <div className="flex items-start justify-between gap-2">
            <SheetTitle
              className="brand-heading text-foreground leading-snug"
              data-testid="drawer-title"
            >
              {event?.title ?? "Untitled event"}
            </SheetTitle>
            <SheetClose
              data-testid="sheet-close"
              className="shrink-0"
            />
          </div>
          {event ? (
            <div className="flex items-center gap-2 flex-wrap mt-1">
              {event.source_type ? (
                <TypeBadge feed_type={event.source_type} />
              ) : null}
              <TlpBadge tlp={event.tlp} />
              <span className="text-xs text-muted-foreground">
                {event.source_name ?? "—"} &middot;{" "}
                {formatRelativeTime(event.observed_at)}
              </span>
            </div>
          ) : null}
          {showNav ? (
            <DrawerNav
              currentIndex={currentIndex}
              totalCount={totalCount}
              onPrev={() => prevEventId && onNavigate(prevEventId)}
              onNext={() => nextEventId && onNavigate(nextEventId)}
            />
          ) : null}
        </SheetHeader>

        {/* Loading skeleton*/}
        {loading ? (
          <div className="p-4 flex flex-col gap-3" data-testid="drawer-loading">
            <div className="animate-pulse bg-muted rounded h-4 w-3/4" />
            <div className="animate-pulse bg-muted rounded h-4 w-full" />
            <div className="animate-pulse bg-muted rounded h-4 w-5/6" />
            <div className="animate-pulse bg-muted rounded h-48 w-full" />
          </div>
        ) : error ? (
          /* Error state — header still visible above*/
          <div className="p-4" data-testid="drawer-error">
            <p className="text-muted-foreground" style={{ fontSize: 16 }}>
              Failed to load event. Please try again.
            </p>
          </div>
        ) : event ? (
          <>
            {/* Section 2 — Description*/}
            <section
              data-testid="drawer-section-description"
              className="p-4 border-b"
            >
              <p
                className="text-foreground"
                style={{ fontSize: 16, lineHeight: 1.7 }}
              >
                {event.description ?? "No description available."}
              </p>
            </section>

            {/* Section 3 — Tags*/}
            <section
              data-testid="drawer-section-tags"
              className="p-4 border-b"
            >
              <p className="brand-caption text-muted-foreground mb-2">TAGS</p>
              <TagEditor eventId={event.id} initialTags={event.tags} />
            </section>

            {/* Section 3b — Score (visible only when score is non-null; hidden for pre-migration events) */}
            <section
              data-testid="drawer-section-score"
              className="p-4 border-b"
            >
              <p className="brand-caption text-muted-foreground mb-2">SCORE</p>
              {event.score != null && event.scored_at != null ? (
                <dl className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <dt className="brand-caption text-muted-foreground w-28 shrink-0">Tier</dt>
                    <dd>
                      <TierBadge tier={classifyTier(event.score)} />
                    </dd>
                  </div>
                  <div className="flex items-center gap-2">
                    <dt className="brand-caption text-muted-foreground w-28 shrink-0">Base score</dt>
                    <dd className="text-xs font-mono text-foreground">{event.score.toFixed(1)}</dd>
                  </div>
                  <div className="flex items-center gap-2">
                    <dt className="brand-caption text-muted-foreground w-28 shrink-0">Current score</dt>
                    <dd className="flex items-center gap-1">
                      <span className="text-xs font-mono text-muted-foreground">
                        {currentScore(event.score, event.scored_at).toFixed(1)}
                      </span>
                      <span className="brand-caption text-muted-foreground">(decay-adjusted)</span>
                    </dd>
                  </div>
                  {event.score_version != null && (
                    <div className="flex items-center gap-2">
                      <dt className="brand-caption text-muted-foreground w-28 shrink-0">Score version</dt>
                      <dd className="text-xs font-mono text-muted-foreground">v{event.score_version}</dd>
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <dt className="brand-caption text-muted-foreground w-28 shrink-0">Scored at</dt>
                    <dd className="text-xs text-muted-foreground">{formatRelativeTime(event.scored_at)}</dd>
                  </div>
                  {event.tags?.includes("burst_cluster") && (
                    <div className="flex items-center gap-2">
                      <dt className="brand-caption text-muted-foreground w-28 shrink-0">Suppressed</dt>
                      <dd>
                        <span className="brand-caption text-orange-300">
                          Suppressed — burst cluster in 1h window
                        </span>
                      </dd>
                    </div>
                  )}
                </dl>
              ) : (
                <p className="text-xs text-muted-foreground">Score not yet computed.</p>
              )}
            </section>

            {/* Section 3b2 — IOCs (Phase 22 Plan 06 §Surface 5) */}
            <IOCsSection eventId={event.id} />

            {/* Section 3b3 — Sandbox Report (Phase 27 SANDBOX-04) */}
            {drawerProjectId && (
              <SandboxReportSection eventId={event.id} projectId={drawerProjectId} />
            )}

            {/* Section 3c — AI Summary */}
            <AISummarySection eventId={event.id} />

            {/* Section 4 — ATT&CK techniques*/}
            <section
              data-testid="drawer-section-techniques"
              className="p-4 border-b"
            >
              <p className="brand-caption text-muted-foreground mb-2">
                ATT&amp;CK TECHNIQUES
              </p>
              {event.attack_techniques.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No techniques linked.
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {event.attack_techniques.map((t) => (
                    <a
                      key={t}
                      href={`https://attack.mitre.org/techniques/${t}/`}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`ATT&CK technique ${t} (opens mitre.org)`}
                      className="inline-flex items-center gap-1"
                    >
                      <Badge
                        variant="outline"
                        className="brand-caption"
                        style={TECH_CHIP_STYLE}
                      >
                        {t}
                      </Badge>
                      <ExternalLink size={10} />
                    </a>
                  ))}
                </div>
              )}
            </section>

            {/* Section 5 — Geo
 M1: EventDetail has no geo_lat/geo_lon fields (geo resolution lands via
 MAP-05). Always renders the fallback copy per-05 spec note.*/}
            <section
              data-testid="drawer-section-geo"
              className="p-4 border-b"
            >
              <p className="brand-caption text-muted-foreground mb-2">
                LOCATION
              </p>
              <p className="text-sm text-muted-foreground">
                No geo data available.
              </p>
            </section>

            {/* Section 6 — Attack Graph*/}
            <section
              data-testid="drawer-section-graph"
              className="p-4 border-b"
            >
              <p className="brand-caption text-muted-foreground mb-2">
                ATTACK GRAPH
              </p>
              <AttackGraph eventId={event.id} height={240} projectId={drawerProjectId} />
            </section>

            {/* Section 7 — Raw STIX / CVE (collapsed by default)*/}
            <section data-testid="drawer-section-raw" className="p-4">
              <details>
                <summary
                  data-testid="drawer-raw-summary"
                  className="brand-caption text-muted-foreground cursor-pointer hover:text-foreground"
                >
                  VIEW RAW DATA
                </summary>
                <pre
                  data-testid="drawer-raw-pre"
                  className="brand-mono mt-2 overflow-x-auto text-muted-foreground p-2 rounded"
                  style={{ background: "hsl(var(--muted))" }}
                >
                  {JSON.stringify(event.raw_stix ?? null, null, 2)}
                </pre>
              </details>
            </section>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
