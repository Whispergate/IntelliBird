"use client";

/**
 * AIScenarioNarrative — Surface 6: per-scenario AI narrative streaming.
 * UI-SPEC §Surface 6 verbatim.
 *
 * Mirrors AISummarySection.tsx exactly:
 *   - POST /draft-narrative → { job_id }
 *   - EventSource GET /api/ai/jobs/{job_id}/stream → token streaming
 *   - brand-mono streaming display + pulse cursor
 *   - on complete: transitions to editable Textarea
 *   - AI-drafted badge + edit metadata (persists after analyst edit)
 *   - 429 budget exhausted: toast + inline message
 *   - SSE error: inline error span
 *   - readOnly: hides Re-draft with AI button
 */

import { useEffect, useRef, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { draftNarrative, patchScenario } from "../lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AIDraftMetadata {
  ai_drafted?: boolean;
  edited_by?: string;
  edited_at?: string;
}

interface AIScenarioNarrativeProps {
  projectId: string;
  reportId: string;
  scenarioId: string;
  /** Pre-loaded narrative text from scenario payload. */
  initialNarrative?: string | null;
  /** Pre-loaded AI draft metadata from scenario payload. */
  initialMetadata?: Record<string, unknown> | null;
  readOnly?: boolean;
  onNarrativeUpdate?: (narrative: string, metadata: Record<string, unknown> | null) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AIScenarioNarrative({
  projectId,
  reportId,
  scenarioId,
  initialNarrative,
  initialMetadata,
  readOnly = false,
  onNarrativeUpdate,
}: AIScenarioNarrativeProps) {
  const [narrativeText, setNarrativeText] = useState<string>(initialNarrative ?? "");
  const [draftMetadata, setDraftMetadata] = useState<AIDraftMetadata | null>(
    (initialMetadata as AIDraftMetadata) ?? null,
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [budgetExhausted, setBudgetExhausted] = useState(false);
  const [streamComplete, setStreamComplete] = useState(!!initialNarrative);

  const eventSourceRef = useRef<EventSource | null>(null);
  const saveDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      if (saveDebounceRef.current) clearTimeout(saveDebounceRef.current);
    };
  }, []);

  async function handleDraftNarrative() {
    // Reset state
    setStreamError(null);
    setBudgetExhausted(false);
    setNarrativeText("");
    setIsStreaming(true);
    setStreamComplete(false);

    // Close any existing stream
    eventSourceRef.current?.close();

    try {
      // POST /draft-narrative — matches draftNarrative helper in lib/api.ts
      let jobId: string;
      try {
        const result = await draftNarrative({ projectId, reportId, scenarioId });
        jobId = result.job_id;
      } catch (e) {
        // Check for 429 budget exhausted
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("429") || msg.toLowerCase().includes("budget")) {
          setBudgetExhausted(true);
          setIsStreaming(false);
          toast.error("Daily AI budget exhausted — resets at 00:00 UTC.");
          return;
        }
        throw e;
      }

      // Open SSE stream — mirror AISummarySection pattern exactly
      const es = new EventSource(`/api/ai/jobs/${jobId}/stream`);
      eventSourceRef.current = es;

      es.onmessage = (event) => {
        setNarrativeText((prev) => prev + event.data);
      };

      es.addEventListener("done", async () => {
        es.close();
        eventSourceRef.current = null;
        setIsStreaming(false);
        setStreamComplete(true);
        // Mark as AI-drafted
        const newMeta: AIDraftMetadata = { ai_drafted: true };
        setDraftMetadata(newMeta);
        // Persist narrative via PATCH
        try {
          setNarrativeText((text) => {
            patchScenario({
              projectId,
              reportId,
              scenarioId,
              body: { ai_draft_narrative: text },
            }).catch(() => {
              // Non-fatal — text is already shown
            });
            return text;
          });
        } catch {
          // Non-fatal
        }
      });

      es.addEventListener("error", (event) => {
        es.close();
        eventSourceRef.current = null;
        setIsStreaming(false);
        const errMsg = (event as MessageEvent).data ?? "Unknown error";
        setStreamError(`— Error: ${errMsg}`);
      });

      // Handle connection-level errors
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          eventSourceRef.current = null;
          setIsStreaming(false);
        }
      };
    } catch (err) {
      setIsStreaming(false);
      const msg = err instanceof Error ? err.message : "Unknown error";
      setStreamError(`— Error: ${msg}`);
    }
  }

  // Debounced PATCH on analyst edit — updates narrative + edit metadata
  function handleNarrativeEdit(value: string) {
    setNarrativeText(value);
    // Mark as edited — update metadata
    const now = new Date().toISOString();
    const updatedMeta: AIDraftMetadata = {
      ...draftMetadata,
      ai_drafted: true,
      edited_at: now,
    };
    setDraftMetadata(updatedMeta);

    if (saveDebounceRef.current) clearTimeout(saveDebounceRef.current);
    saveDebounceRef.current = setTimeout(async () => {
      try {
        await patchScenario({
          projectId,
          reportId,
          scenarioId,
          body: { ai_draft_narrative: value },
        });
        onNarrativeUpdate?.(value, updatedMeta as Record<string, unknown>);
      } catch {
        // Non-fatal on debounce save
      }
    }, 500);
  }

  const hasNarrative = narrativeText.length > 0;
  const hasDraftMetadata = draftMetadata !== null;

  const buttonLabel = isStreaming
    ? "Drafting…"
    : hasNarrative
      ? "Re-draft with AI"
      : "Draft narrative with AI";

  return (
    <div className="mt-3">
      {/* Draft narrative trigger button */}
      {!readOnly && (
        <Button
          variant="outline"
          size="sm"
          disabled={isStreaming}
          onClick={handleDraftNarrative}
          className="w-full"
        >
          {isStreaming ? (
            <Loader2 className="animate-spin mr-1" size={14} />
          ) : (
            <Sparkles className="mr-1" size={14} />
          )}
          {buttonLabel}
        </Button>
      )}

      {/* Budget exhausted inline message — UI-SPEC §Surface 6 */}
      {budgetExhausted && (
        <p className="text-destructive text-xs mt-1">
          Budget exhausted — resets at 00:00 UTC
        </p>
      )}

      {/* Streaming display — brand-mono pattern from */}
      {(hasNarrative || isStreaming) && !streamComplete && (
        <div
          className="brand-mono whitespace-pre-wrap leading-relaxed text-foreground mt-2 rounded-md bg-card p-3 text-xs"
          data-testid="ai-scenario-narrative-streaming"
        >
          {narrativeText}
          {isStreaming && (
            <span
              className="inline-block w-1.5 h-3 bg-[var(--brand-signal)] animate-pulse align-middle ml-0.5"
              aria-hidden="true"
            />
          )}
          {streamError && !isStreaming && (
            <span className="text-destructive text-xs ml-1">{streamError}</span>
          )}
        </div>
      )}

      {/* Completed — editable Textarea with AI-drafted badge */}
      {streamComplete && (
        <div className="mt-2">
          {/* AI-drafted badge — UI-SPEC §Surface 6 verbatim */}
          {hasDraftMetadata && (
            <div className="flex items-center gap-1.5 mb-1">
              <Badge
                variant="outline"
                className="brand-caption bg-purple-500/10 text-purple-300 border-purple-600"
              >
                <Sparkles size={10} className="mr-1" />
                AI-drafted
              </Badge>
              {draftMetadata?.edited_at && (
                <span className="text-xs text-muted-foreground">
                  edited by {draftMetadata.edited_by ?? "analyst"} on{" "}
                  {formatDate(draftMetadata.edited_at)}
                </span>
              )}
            </div>
          )}
          <Textarea
            rows={8}
            value={narrativeText}
            onChange={(e) => handleNarrativeEdit(e.target.value)}
            readOnly={readOnly}
            disabled={readOnly}
            className="text-sm"
            placeholder="AI-drafted narrative will appear here…"
          />
        </div>
      )}

      {/* Stream error without any accumulated text */}
      {streamError && !hasNarrative && !isStreaming && (
        <p className="text-destructive text-xs mt-1">{streamError}</p>
      )}
    </div>
  );
}
