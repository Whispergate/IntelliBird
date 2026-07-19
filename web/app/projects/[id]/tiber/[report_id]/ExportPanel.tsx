"use client";

/**
 * ExportPanel - Surface 7: export buttons with completeness gate + polling.
 * UI-SPEC §Surface 7 verbatim.
 *
 * 3 buttons: Markdown / PDF / STIX.
 * Disabled when sections incomplete OR selectedScenarioCount < 3.
 * Tooltip on disabled listing missing sections.
 * On click: POST /exports → toast → poll /exports?format=… every 3s →
 *   on ready: sonner action toast with download link.
 * Per-format independent loading state.
 * readOnly does NOT apply - export buttons always active on published reports.
 */

import { useRef, useState } from "react";
import { FileDown, FileText, Loader2, Share2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { createExport, listExports, type ReportFormat } from "../lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type FormatLoadingState = Record<ReportFormat, boolean>;

interface ExportPanelProps {
  projectId: string;
  reportId: string;
  /** Missing section names - export disabled when any present */
  completenessGaps: string[];
  /** Number of selected complete scenarios - export disabled when < 3 */
  selectedScenarioCount: number;
  /** Called when an export completes (to trigger HistorySidebar refresh) */
  onExportComplete?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildDisabledReason(
  completenessGaps: string[],
  selectedScenarioCount: number,
): string | null {
  const issues: string[] = [];
  if (completenessGaps.length > 0) {
    issues.push(`Missing: ${completenessGaps.join(", ")}`);
  }
  if (selectedScenarioCount < 3) {
    const needed = 3 - selectedScenarioCount;
    issues.push(
      `Threat Scenarios (only ${selectedScenarioCount} of 3 required scenarios selected)`,
    );
    void needed; // used implicitly in message above
  }
  return issues.length > 0 ? issues.join(". ") : null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ExportPanel({
  projectId,
  reportId,
  completenessGaps,
  selectedScenarioCount,
  onExportComplete,
}: ExportPanelProps) {
  const [loading, setLoading] = useState<FormatLoadingState>({
    markdown: false,
    pdf: false,
    stix: false,
  });

  // Track polling intervals per format
  const pollingRefs = useRef<Record<ReportFormat, ReturnType<typeof setInterval> | null>>({
    markdown: null,
    pdf: null,
    stix: null,
  });

  const disabledReason = buildDisabledReason(completenessGaps, selectedScenarioCount);
  const isDisabled = disabledReason !== null;

  function setFormatLoading(format: ReportFormat, value: boolean) {
    setLoading((prev) => ({ ...prev, [format]: value }));
  }

  function stopPolling(format: ReportFormat) {
    if (pollingRefs.current[format]) {
      clearInterval(pollingRefs.current[format]!);
      pollingRefs.current[format] = null;
    }
  }

  async function handleExport(format: ReportFormat) {
    if (loading[format]) return;
    setFormatLoading(format, true);

    let exportId: string;
    let pollingStarted: number;

    try {
      const exp = await createExport({ projectId, reportId, format });
      exportId = exp.id;
      pollingStarted = Date.now();

      const formatLabel = format === "markdown" ? "Markdown" : format.toUpperCase();
      toast.success(`Generating ${formatLabel}…`);
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      toast.error(`Export failed: ${detail}`);
      setFormatLoading(format, false);
      return;
    }

    // Poll every 3s for export completion
    stopPolling(format);
    pollingRefs.current[format] = setInterval(async () => {
      try {
        const exports = await listExports({ projectId, reportId, format });
        // Find the export that was started after polling began
        const ready = exports.find(
          (e) =>
            e.id === exportId ||
            new Date(e.generated_at).getTime() >= pollingStarted - 5000,
        );

        if (ready) {
          stopPolling(format);
          setFormatLoading(format, false);
          onExportComplete?.();

          const downloadUrl = `/api/projects/${projectId}/tiber/reports/${reportId}/exports/${ready.id}/download`;
          toast.success("Export ready.", {
            action: {
              label: `Download ${ready.filename}`,
              onClick: () => {
                const link = document.createElement("a");
                link.href = downloadUrl;
                link.download = ready.filename;
                link.click();
              },
            },
            duration: 10000,
          });
        }
      } catch {
        stopPolling(format);
        setFormatLoading(format, false);
        toast.error("Export status check failed.");
      }
    }, 3000);
  }

  const BUTTONS: { format: ReportFormat; label: string; Icon: typeof FileText }[] = [
    { format: "markdown", label: "Export Markdown", Icon: FileText },
    { format: "pdf", label: "Export PDF", Icon: FileDown },
    { format: "stix", label: "Export STIX", Icon: Share2 },
  ];

  return (
    <Card className="mb-6">
      <CardHeader className="pb-3">
        <CardTitle className="brand-heading">Export</CardTitle>
      </CardHeader>
      <CardContent>
        <TooltipProvider delayDuration={300}>
          <div className="flex flex-wrap gap-3">
            {BUTTONS.map(({ format, label, Icon }) => {
              const isLoading = loading[format];
              const disabled = isDisabled || isLoading;

              return (
                <Tooltip key={format}>
                  <TooltipTrigger asChild>
                    <span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={disabled}
                        onClick={() => handleExport(format)}
                        className={disabled && !isLoading ? "opacity-50 cursor-not-allowed" : ""}
                      >
                        {isLoading ? (
                          <Loader2 size={14} className="animate-spin mr-1" />
                        ) : (
                          <Icon size={14} className="mr-1" />
                        )}
                        {label}
                      </Button>
                    </span>
                  </TooltipTrigger>
                  {isDisabled && disabledReason && (
                    <TooltipContent side="bottom" className="text-xs max-w-72">
                      {disabledReason}
                    </TooltipContent>
                  )}
                </Tooltip>
              );
            })}
          </div>

          {/* Validation summary - shown when export is blocked */}
          {isDisabled && (
            <p className="text-destructive text-xs mt-3">
              {completenessGaps.length + (selectedScenarioCount < 3 ? 1 : 0)} issue(s) must be
              resolved before export. See missing fields below.
            </p>
          )}
        </TooltipProvider>
      </CardContent>
    </Card>
  );
}
