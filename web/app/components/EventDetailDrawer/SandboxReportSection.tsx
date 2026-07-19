"use client";

/**
 * SandboxReportSection - (SANDBOX-04).
 * Collapsible section in EventDetailDrawer showing sandbox analysis results.
 * Renders: verdict badge, score bar, MITRE techniques list, network IOCs, process tree.
 * Fetches GET /api/projects/{projectId}/events/{eventId}/sandbox-report on mount.
 */

import { useEffect, useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { ChevronDown } from "lucide-react";
import { getSandboxReport, type SandboxReportRead } from "@/app/api-client";

interface Props {
  eventId: string;
  projectId: string;
}

const VERDICT_COLORS: Record<string, string> = {
  malicious: "bg-red-100 text-red-800 border-red-200",
  suspicious: "bg-amber-100 text-amber-800 border-amber-200",
  clean: "bg-green-100 text-green-800 border-green-200",
  unknown: "bg-gray-100 text-gray-600 border-gray-200",
};

export function SandboxReportSection({ eventId, projectId }: Props) {
  const [report, setReport] = useState<SandboxReportRead | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSandboxReport(projectId, eventId)
      .then(setReport)
      .catch((e) => setError(String(e)));
  }, [eventId, projectId]);

  // Still loading - show nothing (no spinner to avoid layout shift)
  if (report === undefined) return null;
  // No report for this event - section hidden
  if (report === null) return null;
  if (error) return null;

  const verdictClass = VERDICT_COLORS[report.verdict ?? "unknown"] ?? VERDICT_COLORS.unknown;

  return (
    <Collapsible defaultOpen={false} className="border-t border-border">
      <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/40">
        <span>Sandbox Report</span>
        <div className="flex items-center gap-2">
          {report.verdict && (
            <Badge variant="outline" className={`text-xs ${verdictClass}`}>
              {report.verdict}
            </Badge>
          )}
          {report.score !== null && (
            <span className="text-xs text-muted-foreground">
              Score: {report.score}/100
            </span>
          )}
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        </div>
      </CollapsibleTrigger>
      <CollapsibleContent className="px-4 pb-4 space-y-3">
        {/* Status / provider row */}
        <div className="text-xs text-muted-foreground">
          Provider: <span className="font-medium text-foreground">{report.provider}</span>
          {" · "}
          Status: <span className="font-medium text-foreground">{report.status}</span>
        </div>

        {/* MITRE ATT&CK Techniques */}
        {report.techniques && report.techniques.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">ATT&amp;CK Techniques</p>
            <div className="flex flex-wrap gap-1">
              {report.techniques.map((t) => (
                <Badge key={t} variant="secondary" className="text-xs font-mono">
                  {t}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Network IOCs */}
        {report.network_iocs && report.network_iocs.length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">
              Network IOCs ({report.network_iocs.length})
            </p>
            <ul className="space-y-0.5">
              {report.network_iocs.slice(0, 20).map((ioc, i) => (
                <li key={i} className="text-xs font-mono text-foreground">
                  {ioc}
                </li>
              ))}
              {report.network_iocs.length > 20 && (
                <li className="text-xs text-muted-foreground">
                  +{report.network_iocs.length - 20} more
                </li>
              )}
            </ul>
          </div>
        )}

        {/* Process Tree */}
        {report.process_tree && Object.keys(report.process_tree).length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">Process Tree</p>
            <pre className="text-xs bg-muted rounded p-2 overflow-auto max-h-48 whitespace-pre-wrap">
              {JSON.stringify(report.process_tree, null, 2)}
            </pre>
          </div>
        )}

        {/* Timing */}
        <div className="text-xs text-muted-foreground">
          Submitted: {new Date(report.submitted_at).toLocaleString()}
          {report.completed_at && (
            <> · Completed: {new Date(report.completed_at).toLocaleString()}</>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
