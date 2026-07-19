"use client";

/**
 * DiffView - (UI-SPEC §Surface 6 §"Diff vs previous").
 *
 * Lazy-loaded by ScanDetailClient only when Diff tab is first selected.
 * Calls getScanDiff(projectId, scanId) on mount.
 *
 * Three shadcn Collapsible sections (default expanded):
 *   NEW     - bg-green-500/10 border-l-4 border-green-500
 *   CHANGED - "Changed" label in text-orange-500; two-column old/new raw_bbot display
 *   RESOLVED - bg-muted/40; "Resolved" label in text-muted-foreground
 *
 * Empty section copy byte-exact per UI-SPEC §Copywriting Contract.
 */

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { DiffChangedEntry, DiffEntry, EASMDiff } from "../../lib/api";
import { getScanDiff } from "../../lib/api";

// ---------------------------------------------------------------------------
// Section header
// ---------------------------------------------------------------------------

function SectionHeader({
  title,
  count,
  isOpen,
}: {
  title: string;
  count: number;
  isOpen: boolean;
}) {
  return (
    <div className="flex items-center justify-between w-full py-3 px-4">
      <div className="flex items-center gap-3">
        <span className="text-[22px] font-medium leading-[1.3]">{title}</span>
        <span className="brand-caption text-muted-foreground">
          {count} finding{count !== 1 ? "s" : ""}
        </span>
      </div>
      {isOpen ? (
        <ChevronUp className="w-4 h-4 text-muted-foreground" />
      ) : (
        <ChevronDown className="w-4 h-4 text-muted-foreground" />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// NEW section row
// ---------------------------------------------------------------------------

function NewRow({ entry }: { entry: DiffEntry }) {
  return (
    <div className="px-4 py-2 bg-green-500/10 border-l-4 border-green-500 mb-1 rounded-sm">
      <div className="flex items-center gap-3">
        <span className="brand-caption text-muted-foreground">{entry.bbot_event_type}</span>
        <span className="font-mono text-[12px] text-foreground flex-1 truncate">
          {entry.canonical_target}
        </span>
        {entry.module && (
          <span className="brand-caption text-muted-foreground">{entry.module}</span>
        )}
        {entry.severity && (
          <span className="brand-caption text-muted-foreground uppercase">{entry.severity}</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CHANGED section row
// ---------------------------------------------------------------------------

function ChangedRow({ entry }: { entry: DiffChangedEntry }) {
  return (
    <div className="px-4 py-2 mb-1 rounded-sm border border-border/40">
      <div className="flex items-center gap-2 mb-2">
        <span className="brand-caption text-muted-foreground">{entry.bbot_event_type}</span>
        <span className="font-mono text-[12px] text-foreground flex-1 truncate">
          {entry.canonical_target}
        </span>
        <span className="brand-caption text-orange-500 font-medium">Changed</span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="brand-caption text-muted-foreground mb-1">Previous</p>
          <pre className="font-mono text-[11px] text-foreground bg-card/60 rounded p-2 overflow-x-auto text-wrap break-all whitespace-pre-wrap">
            {JSON.stringify(entry.previous, null, 2)}
          </pre>
        </div>
        <div>
          <p className="brand-caption text-muted-foreground mb-1">Current</p>
          <pre className="font-mono text-[11px] text-foreground bg-card/60 rounded p-2 overflow-x-auto text-wrap break-all whitespace-pre-wrap">
            {JSON.stringify(entry.current, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RESOLVED section row
// ---------------------------------------------------------------------------

function ResolvedRow({ entry }: { entry: DiffEntry }) {
  return (
    <div className="px-4 py-2 bg-muted/40 mb-1 rounded-sm">
      <div className="flex items-center gap-3">
        <span className="brand-caption text-muted-foreground">{entry.bbot_event_type}</span>
        <span className="font-mono text-[12px] text-muted-foreground flex-1 truncate">
          {entry.canonical_target}
        </span>
        <span className="brand-caption text-muted-foreground">Resolved</span>
        {entry.module && (
          <span className="brand-caption text-muted-foreground">{entry.module}</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DiffView
// ---------------------------------------------------------------------------

interface DiffViewProps {
  projectId: string;
  scanId: string;
}

export function DiffView({ projectId, scanId }: DiffViewProps) {
  const [diff, setDiff] = useState<EASMDiff | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Collapsible open state
  const [newOpen, setNewOpen] = useState(true);
  const [changedOpen, setChangedOpen] = useState(true);
  const [resolvedOpen, setResolvedOpen] = useState(true);

  // -----------------------------------------------------------------------
  // Fetch diff on mount
  // -----------------------------------------------------------------------
  const fetchDiff = useCallback(async () => {
    setLoading(true);
    setError(null);

    // 3s timeout
    const timer = setTimeout(() => {
      setLoading(false);
      setError(
        "Could not compute diff. The previous scan may have been deleted or the server is unavailable.",
      );
    }, 3000);

    try {
      const result = await getScanDiff(projectId, scanId);
      clearTimeout(timer);
      setDiff(result);
    } catch (err) {
      clearTimeout(timer);
      const msg = err instanceof Error ? err.message : "error";
      setError(
        `Could not compute diff. The previous scan may have been deleted or the server is unavailable. ${msg}`,
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, scanId]);

  useEffect(() => {
    fetchDiff();
  }, [fetchDiff]);

  // -----------------------------------------------------------------------
  // Loading state
  // -----------------------------------------------------------------------
  if (loading) {
    return (
      <div className="flex justify-center py-12" data-testid="diff-spinner">
        <div className="w-6 h-6 rounded-full border-2 border-muted border-t-foreground animate-spin" />
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Error state
  // -----------------------------------------------------------------------
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3">
        <p className="text-sm text-muted-foreground text-center max-w-md">
          {error}
        </p>
        <button
          type="button"
          className="text-sm text-foreground underline hover:no-underline"
          onClick={fetchDiff}
        >
          Try again
        </button>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // No prior scan state
  // -----------------------------------------------------------------------
  if (!diff || diff.prior_scan_id === null) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
        <h2 className="text-[22px] font-medium leading-[1.3]">
          No previous scan to compare
        </h2>
        <p className="text-muted-foreground max-w-md leading-[1.7]">
          This is the first scan for this project. Diff view requires at least
          two completed scans.
        </p>
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Three-section diff view
  // -----------------------------------------------------------------------
  return (
    <div className="space-y-2" data-testid="diff-sections">
      {/* NEW section */}
      <div className="rounded-md border border-border overflow-hidden">
        <Collapsible open={newOpen} onOpenChange={setNewOpen}>
          <CollapsibleTrigger className="w-full bg-card hover:bg-card/80 transition-colors border-b border-border/40 data-[state=open]:border-b data-[state=closed]:border-b-0">
            <SectionHeader
              title="NEW"
              count={diff.new.length}
              isOpen={newOpen}
            />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="p-4">
              {diff.new.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No new findings compared to the previous scan.
                </p>
              ) : (
                diff.new.map((entry, i) => (
                  <NewRow key={`${entry.bbot_event_type}-${entry.canonical_target}-${i}`} entry={entry} />
                ))
              )}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>

      {/* CHANGED section */}
      <div className="rounded-md border border-border overflow-hidden">
        <Collapsible open={changedOpen} onOpenChange={setChangedOpen}>
          <CollapsibleTrigger className="w-full bg-card hover:bg-card/80 transition-colors border-b border-border/40 data-[state=open]:border-b data-[state=closed]:border-b-0">
            <SectionHeader
              title="CHANGED"
              count={diff.changed.length}
              isOpen={changedOpen}
            />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="p-4">
              {diff.changed.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No changed findings.
                </p>
              ) : (
                diff.changed.map((entry, i) => (
                  <ChangedRow key={`${entry.bbot_event_type}-${entry.canonical_target}-${i}`} entry={entry} />
                ))
              )}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>

      {/* RESOLVED section */}
      <div className="rounded-md border border-border overflow-hidden">
        <Collapsible open={resolvedOpen} onOpenChange={setResolvedOpen}>
          <CollapsibleTrigger className="w-full bg-card hover:bg-card/80 transition-colors border-b border-border/40 data-[state=open]:border-b data-[state=closed]:border-b-0">
            <SectionHeader
              title="RESOLVED"
              count={diff.resolved.length}
              isOpen={resolvedOpen}
            />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="p-4">
              {diff.resolved.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No resolved findings. Prior findings are still present.
                </p>
              ) : (
                diff.resolved.map((entry, i) => (
                  <ResolvedRow key={`${entry.bbot_event_type}-${entry.canonical_target}-${i}`} entry={entry} />
                ))
              )}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  );
}
