"use client";

/**
 * IOCBulkImportDialog — Phase 22 Plan 06 (UI-SPEC §Surface 3).
 *
 * 4-step stepper: Upload → Configure → Preview (dry-run) → Import (async polling).
 *
 * Backend contract (Plan 22-05):
 *   - POST /api/iocs/bulk-import?dry_run=true  → IOCBulkImportDryRun
 *   - POST /api/iocs/bulk-import               → IOCBulkImportEnqueued {job_id}
 *   - GET  /api/jobs/{job_id}                  → IOCJobStatus
 */

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Upload, X, Check, AlertCircle } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  dryRunBulkImport,
  submitBulkImport,
  pollJobStatus,
  type IOCBulkImportFormat,
  type IOCBulkImportDryRun,
} from "@/app/api-client";

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;
const MAX_BYTES = 5 * 1024 * 1024;
const MAX_ROWS = 10_000;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  onComplete: () => void;
}

function detectFormat(file: File): IOCBulkImportFormat | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".csv")) return "csv";
  if (name.endsWith(".json")) {
    return "json";
  }
  if (name.endsWith(".stix") || name.endsWith(".stix.json")) return "stix";
  if (file.type === "text/csv") return "csv";
  if (file.type === "application/stix+json") return "stix";
  if (file.type === "application/json") return "json";
  return null;
}

function StepperBar({ step }: { step: 1 | 2 | 3 | 4 }) {
  const labels = ["Upload", "Configure", "Preview", "Import"] as const;
  return (
    <div className="flex items-center gap-2 px-2 py-3" data-testid="bulk-stepper">
      {labels.map((label, i) => {
        const idx = (i + 1) as 1 | 2 | 3 | 4;
        const isActive = step === idx;
        const isComplete = step > idx;
        const cls = isActive
          ? "bg-[var(--brand-signal)] text-background"
          : isComplete
            ? "bg-green-500/30 text-green-300"
            : "bg-muted text-muted-foreground";
        return (
          <div key={label} className="flex items-center gap-2">
            <span
              className={`inline-flex items-center justify-center h-6 w-6 rounded-full text-[12px] font-medium ${cls}`}
              data-testid={`step-circle-${idx}`}
            >
              {idx}
            </span>
            <span className="text-[12px] text-muted-foreground">{label}</span>
            {idx < 4 && (
              <span className="w-8 border-t border-border mx-1" />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function IOCBulkImportDialog({
  open,
  onOpenChange,
  projectId,
  onComplete,
}: Props) {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [file, setFile] = useState<File | null>(null);
  const [body, setBody] = useState<string>("");
  const [format, setFormat] = useState<IOCBulkImportFormat>("csv");
  const [defaultConfidence, setDefaultConfidence] = useState<string>("0.7");
  const [targetProject, setTargetProject] = useState<string>(projectId);
  const [fileError, setFileError] = useState<string | null>(null);

  const [dryRunResult, setDryRunResult] = useState<IOCBulkImportDryRun | null>(
    null,
  );
  const [running, setRunning] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [importComplete, setImportComplete] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importedCount, setImportedCount] = useState(0);
  const pollTimerRef = useRef<number | null>(null);

  function reset() {
    setStep(1);
    setFile(null);
    setBody("");
    setFormat("csv");
    setDefaultConfidence("0.7");
    setTargetProject(projectId);
    setFileError(null);
    setDryRunResult(null);
    setRunning(false);
    setJobId(null);
    setProgressPct(0);
    setImportComplete(false);
    setImportError(null);
    setImportedCount(0);
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }

  useEffect(() => {
    if (!open) reset();
    return () => {
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function handleFile(f: File) {
    setFileError(null);
    if (f.size > MAX_BYTES) {
      setFileError("File exceeds 5 MB. Split it before uploading.");
      return;
    }
    const text = await f.text();
    // Approximate row count from newline count for CSV/JSON (best-effort).
    const newlineCount = (text.match(/\n/g) ?? []).length;
    if (newlineCount > MAX_ROWS) {
      setFileError("File exceeds 10 000 rows. Split it before uploading.");
      return;
    }
    setFile(f);
    setBody(text);
    const detected = detectFormat(f);
    if (detected) setFormat(detected);
  }

  async function runDryRun() {
    setRunning(true);
    try {
      const result = await dryRunBulkImport({
        projectId: targetProject === "global" ? undefined : targetProject,
        format,
        body,
      });
      setDryRunResult(result);
      setStep(3);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`Dry-run failed. ${msg}`);
    } finally {
      setRunning(false);
    }
  }

  async function startPoll(currentJobId: string) {
    const startTs = Date.now();
    const tick = async () => {
      try {
        const status = await pollJobStatus(currentJobId);
        if (status.total && status.processed !== undefined) {
          const pct = Math.min(100, Math.round((status.processed / status.total) * 100));
          setProgressPct(pct);
        }
        if (status.status === "complete") {
          setImportComplete(true);
          setImportedCount((status.inserted ?? 0) + (status.updated ?? 0));
          setProgressPct(100);
          toast.success(
            `Imported ${(status.inserted ?? 0) + (status.updated ?? 0)} IOCs.`,
          );
          onComplete();
          return;
        }
        if (status.status === "failed") {
          setImportError(status.error ?? "Import failed.");
          toast.error(`Import failed. ${status.error ?? ""}`);
          return;
        }
        if (Date.now() - startTs > POLL_TIMEOUT_MS) {
          toast.error(
            "Import is taking longer than expected. Check IOCs tab — rows will appear when complete.",
          );
          onOpenChange(false);
          return;
        }
        pollTimerRef.current = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setImportError(msg);
        toast.error(`Polling failed. ${msg}`);
      }
    };
    pollTimerRef.current = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
  }

  async function confirmImport() {
    setStep(4);
    setRunning(true);
    setImportError(null);
    try {
      const { job_id } = await submitBulkImport({
        projectId: targetProject === "global" ? undefined : targetProject,
        format,
        body,
      });
      setJobId(job_id);
      void startPoll(job_id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setImportError(msg);
      toast.error(`Import failed to start. ${msg}`);
    } finally {
      setRunning(false);
    }
  }

  function handleDialogChange(next: boolean) {
    if (!next && step === 4 && !importComplete && !importError) {
      const ok = window.confirm(
        "Import is in progress. Close dialog and let it finish in the background?",
      );
      if (!ok) return;
    }
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={handleDialogChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import IOCs</DialogTitle>
          <DialogDescription>
            Upload CSV, JSON, or STIX 2.1. Run a dry-run first to preview the
            result.
          </DialogDescription>
        </DialogHeader>

        <StepperBar step={step} />

        {/* Step 1 — Upload */}
        {step === 1 && (
          <div className="space-y-4">
            <label
              className="border-2 border-dashed border-border rounded-md p-8 flex flex-col items-center justify-center gap-3 hover:border-[var(--brand-signal)] hover:bg-card/40 transition-colors cursor-pointer"
              data-testid="bulk-dropzone"
            >
              <Upload className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-foreground">
                Drag and drop a file here, or click to browse.
              </p>
              <p className="brand-caption text-muted-foreground">
                CSV · JSON · STIX 2.1 bundle · max 10 000 rows · 5 MB
              </p>
              <input
                type="file"
                accept=".csv,.json,.stix,application/json,text/csv,application/stix+json"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void handleFile(f);
                }}
              />
            </label>
            {file && (
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="font-mono">{file.name}</span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setFile(null);
                    setBody("");
                  }}
                  aria-label="Remove file"
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            )}
            {fileError && (
              <p className="text-destructive text-sm">{fileError}</p>
            )}
            <div className="flex justify-end">
              <Button
                onClick={() => setStep(2)}
                disabled={!file || !!fileError}
              >
                Continue
              </Button>
            </div>
          </div>
        )}

        {/* Step 2 — Configure */}
        {step === 2 && (
          <div className="space-y-4">
            <div className="flex flex-col gap-2">
              <Label className="text-xs">Detected format</Label>
              <Select
                value={format}
                onValueChange={(v) => setFormat(v as IOCBulkImportFormat)}
              >
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="csv">csv</SelectItem>
                  <SelectItem value="json">json</SelectItem>
                  <SelectItem value="stix">stix</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label className="text-xs">Target project</Label>
              <Select value={targetProject} onValueChange={setTargetProject}>
                <SelectTrigger className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={projectId}>This project</SelectItem>
                  <SelectItem value="global">Global (all projects)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="default-conf" className="text-xs">
                Default confidence
              </Label>
              <Input
                id="default-conf"
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={defaultConfidence}
                onChange={(e) => setDefaultConfidence(e.target.value)}
                className="h-9 w-32 font-mono"
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label className="text-xs">Default TTL</Label>
              <p className="text-[12px] text-muted-foreground">
                Type-aware (per CONTEXT.md table)
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setStep(1)}>
                Back
              </Button>
              <Button
                variant="outline"
                onClick={() => void runDryRun()}
                disabled={running}
              >
                {running ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    Running…
                  </>
                ) : (
                  "Run dry-run"
                )}
              </Button>
            </div>
          </div>
        )}

        {/* Step 3 — Preview */}
        {step === 3 && dryRunResult && (
          <div className="space-y-4">
            <div className="rounded-md border border-border bg-card p-4 grid grid-cols-4 gap-4">
              <SummaryStat
                label="Insert"
                value={dryRunResult.would_insert}
                colorClass="text-green-300"
              />
              <SummaryStat
                label="Update"
                value={dryRunResult.would_update}
                colorClass="text-foreground"
              />
              <SummaryStat
                label="Skip"
                value={dryRunResult.would_skip}
                colorClass="text-muted-foreground"
              />
              <SummaryStat
                label="Errors"
                value={dryRunResult.errors.length}
                colorClass="text-destructive"
              />
            </div>
            {dryRunResult.errors.length > 0 && (
              <details
                open={dryRunResult.errors.length <= 5}
                className="rounded-md border border-border bg-card/40"
              >
                <summary className="px-3 py-2 cursor-pointer text-sm text-muted-foreground">
                  View {dryRunResult.errors.length} errors
                </summary>
                <div className="px-3 pb-2 max-h-64 overflow-y-auto">
                  {dryRunResult.errors.map((e, i) => (
                    <div
                      key={i}
                      className="flex items-baseline gap-3 py-1.5 border-b border-border/40 last:border-b-0"
                    >
                      <span className="font-mono text-[12px] text-destructive shrink-0 w-12">
                        L{e.line}
                      </span>
                      <span className="font-mono text-[12px] text-muted-foreground shrink-0 w-24 truncate">
                        {e.value}
                      </span>
                      <span className="text-[12px] text-foreground">
                        {e.error}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setStep(2)}>
                Back
              </Button>
              {dryRunResult.would_insert + dryRunResult.would_update === 0 ? (
                <Button variant="outline" onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
              ) : (
                <Button onClick={() => void confirmImport()}>
                  Confirm import
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Step 4 — Import in progress / complete */}
        {step === 4 && (
          <div className="flex flex-col items-center justify-center py-12 gap-4">
            {importError ? (
              <>
                <AlertCircle className="h-8 w-8 text-destructive" />
                <p className="text-foreground">{importError}</p>
                <Button onClick={() => onOpenChange(false)}>Close</Button>
              </>
            ) : importComplete ? (
              <>
                <Check className="h-8 w-8 text-green-300" />
                <p className="text-foreground">
                  Imported {importedCount} IOCs.
                </p>
                <Button onClick={() => onOpenChange(false)}>Done</Button>
              </>
            ) : (
              <>
                <Loader2 className="h-8 w-8 animate-spin text-[var(--brand-signal)]" />
                <p className="text-foreground">Importing IOCs…</p>
                {jobId && (
                  <p className="brand-caption text-muted-foreground font-mono">
                    Job {jobId}
                  </p>
                )}
                <div className="w-64 h-1.5 bg-card rounded-sm overflow-hidden">
                  <div
                    className="h-full bg-[var(--brand-signal)] transition-[width]"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function SummaryStat({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: number;
  colorClass: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <p className="brand-caption text-muted-foreground uppercase">{label}</p>
      <p
        className={`text-[22px] font-medium leading-[1.3] ${colorClass}`}
      >
        {value}
      </p>
    </div>
  );
}
