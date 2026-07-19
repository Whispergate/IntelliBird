"use client";

/**
 * AISummarySection
 * UI-SPEC §Surface 1 - EventDetailDrawer AI Summary section.
 *
 * Responsibilities:
 *   - "Summarise" / "Re-summarise" / "Summarising…" button lifecycle
 *   - POST /api/events/{id}/ai/summarise → {job_id}
 *   - Opens EventSource at GET /api/ai/jobs/{job_id}/stream
 *   - Accumulates SSE data: tokens into a useState string
 *   - Streaming cursor while isStreaming === true
 *   - event: done → clears cursor, marks complete
 *   - event: error → shows inline error below streamed text
 *   - 429 → inline budget-exhausted message + sonner toast
 *   - Truncation footer detection (substring "- Content exceeded")
 *   - Below summary: AISuggestionChip strip from GET /api/events/{id}/ai/suggestions
 *   - Cleanup: EventSource.close() on unmount
 */

import { useEffect, useRef, useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { AISuggestionChip } from "./AISuggestionChip";
import type { AISuggestion, SuggestionStatus } from "./AISuggestionChip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AISummarySectionProps {
  eventId: string;
  /** Pre-loaded summary text from the event payload (if already summarised). */
  aiSummary?: string | null;
  /** Pre-loaded suggestions from the event payload. */
  initialSuggestions?: AISuggestion[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TRUNCATION_MARKER = "- Content exceeded";

function detectTruncation(text: string): { body: string; footer: string | null } {
  const idx = text.lastIndexOf(TRUNCATION_MARKER);
  if (idx === -1) return { body: text, footer: null };
  // Split at the marker line - keep all text up to and including the footer
  const footer = text.slice(idx).trim();
  const body = text.slice(0, idx).trimEnd();
  return { body, footer };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AISummarySection({
  eventId,
  aiSummary,
  initialSuggestions = [],
}: AISummarySectionProps) {
  const [summaryText, setSummaryText] = useState<string>(aiSummary ?? "");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [budgetExhausted, setBudgetExhausted] = useState(false);
  const [suggestions, setSuggestions] = useState<AISuggestion[]>(initialSuggestions);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);

  // Fetch suggestions after a summary completes
  async function fetchSuggestions() {
    setLoadingSuggestions(true);
    try {
      const res = await fetch(`/api/events/${eventId}/ai/suggestions`);
      if (!res.ok) return;
      const data: AISuggestion[] = await res.json();
      setSuggestions(data);
    } catch {
      // Non-fatal - suggestions stay empty
    } finally {
      setLoadingSuggestions(false);
    }
  }

  // Hydrate from persisted summary if not pre-loaded.
  // /api/events/{id}/ai/summary returns the latest ai_summaries row so the
  // narrative survives drawer close/reopen and Redis chunk TTL expiry.
  useEffect(() => {
    if (aiSummary) return; // already pre-loaded
    let cancelled = false;
    async function loadCached() {
      try {
        const res = await fetch(`/api/events/${eventId}/ai/summary`);
        if (!res.ok) return;
        const data: { summary_text: string } = await res.json();
        if (!cancelled && data.summary_text) {
          setSummaryText(data.summary_text);
        }
      } catch {
        // Non-fatal - user can click Summarise.
      }
    }
    loadCached();
    fetchSuggestions();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  async function handleSummarise() {
    // Reset state
    setStreamError(null);
    setBudgetExhausted(false);
    setSummaryText("");
    setIsStreaming(true);

    // Close any existing stream
    eventSourceRef.current?.close();

    try {
      const res = await fetch(`/api/events/${eventId}/ai/summarise`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });

      if (res.status === 429) {
        // Budget exhausted - UI-SPEC §Surface 7 + §Copywriting Contract
        setBudgetExhausted(true);
        setIsStreaming(false);
        toast.error("Daily AI budget exhausted - resets at 00:00 UTC.");
        return;
      }

      if (!res.ok) {
        const text = await res.text().catch(() => "Unknown error.");
        setStreamError(`- Error: ${text}`);
        setIsStreaming(false);
        return;
      }

      const { job_id }: { job_id: string } = await res.json();

      // Open SSE stream
      const es = new EventSource(`/api/ai/jobs/${job_id}/stream`);
      eventSourceRef.current = es;

      es.onmessage = (event) => {
        setSummaryText((prev) => prev + event.data);
      };

      es.addEventListener("done", () => {
        es.close();
        eventSourceRef.current = null;
        setIsStreaming(false);
        // Fetch suggestions now that the summary is complete
        fetchSuggestions();
      });

      es.addEventListener("error", (event) => {
        es.close();
        eventSourceRef.current = null;
        setIsStreaming(false);
        const errMsg = (event as MessageEvent).data ?? "Unknown error";
        setStreamError(`- Error: ${errMsg}`);
      });

      // Handle connection-level errors (network, etc.)
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          eventSourceRef.current = null;
          setIsStreaming(false);
        }
      };
    } catch (err) {
      setIsStreaming(false);
      const msg = err instanceof Error ? err.message : "Unknown error";
      setStreamError(`- Error: ${msg}`);
    }
  }

  const hasSummary = summaryText.length > 0;
  const buttonLabel = isStreaming ? "Summarising…" : hasSummary ? "Re-summarise" : "Summarise";

  const { body, footer } = detectTruncation(summaryText);
  const pendingCount = suggestions.filter((s) => s.status === "pending").length;

  return (
    <>
      <Separator />
      <section
        data-testid="ai-summary-section"
        className="p-4 border-b"
      >
        {/* Section header row */}
        <div className="flex items-center justify-between mb-2">
          <p className="brand-caption text-muted-foreground">AI SUMMARY</p>
          <Button
            variant="outline"
            size="sm"
            disabled={isStreaming}
            onClick={handleSummarise}
            aria-label={buttonLabel}
          >
            {isStreaming ? (
              <Loader2 className="animate-spin mr-1" size={16} />
            ) : (
              <Sparkles className="mr-1" size={16} />
            )}
            {buttonLabel}
          </Button>
        </div>

        {/* Budget exhausted inline message - UI-SPEC §Surface 7 */}
        {budgetExhausted && (
          <p className="text-destructive text-xs mt-1">
            Budget exhausted - resets at 00:00 UTC
          </p>
        )}

        {/* Summary body - shown once streaming starts or pre-loaded summary exists */}
        {(hasSummary || isStreaming) && (
          <div
            className="leading-relaxed text-foreground mt-2 rounded-md bg-card p-3 text-[13px]"
            data-testid="ai-summary-body"
          >
            <ReactMarkdown
              components={{
                h1: ({ children }) => <p className="text-foreground font-semibold mt-2 mb-0.5 text-[13px]">{children}</p>,
                h2: ({ children }) => <p className="text-foreground font-semibold mt-2 mb-0.5 text-[13px]">{children}</p>,
                h3: ({ children }) => <p className="text-foreground font-semibold mt-1.5 mb-0.5 text-[13px]">{children}</p>,
                p: ({ children }) => <p className="text-foreground my-1 text-[13px]">{children}</p>,
                strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
                em: ({ children }) => <em className="italic text-foreground">{children}</em>,
                ul: ({ children }) => <ul className="my-1 pl-4 list-disc text-[13px]">{children}</ul>,
                ol: ({ children }) => <ol className="my-1 pl-4 list-decimal text-[13px]">{children}</ol>,
                li: ({ children }) => <li className="text-foreground my-0.5">{children}</li>,
                code: ({ children }) => <code className="bg-muted px-1 rounded text-[12px] text-foreground">{children}</code>,
              }}
            >
              {body}
            </ReactMarkdown>
            {/* Streaming cursor */}
            {isStreaming && (
              <span
                className="inline-block w-1.5 h-3 bg-[var(--brand-signal)] animate-pulse align-middle ml-0.5"
                aria-hidden="true"
              />
            )}
            {/* Inline stream error */}
            {streamError && !isStreaming && (
              <span className="text-destructive text-xs ml-1">{streamError}</span>
            )}
          </div>
        )}

        {/* Truncation footer - UI-SPEC §1b */}
        {footer && !isStreaming && (
          <p className="text-muted-foreground text-xs mt-2 border-t border-border pt-2">
            {footer}
          </p>
        )}

        {/* Stream error without any accumulated text */}
        {streamError && !hasSummary && !isStreaming && (
          <p className="text-destructive text-xs mt-1">{streamError}</p>
        )}

        {/* AI Suggestions strip - UI-SPEC §1c */}
        {!loadingSuggestions && suggestions.length > 0 && (
          <div className="mt-4">
            <div className="flex items-center gap-2 mb-2">
              <p className="brand-caption text-muted-foreground uppercase text-xs">
                AI Suggestions
              </p>
              <Badge
                variant="outline"
                className={[
                  "brand-caption",
                  pendingCount > 0
                    ? "border-[var(--brand-signal)]"
                    : "border-muted-foreground/40",
                ].join(" ")}
              >
                {pendingCount} pending
              </Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <AISuggestionChip
                  key={s.id}
                  suggestion={s}
                  onChange={(next: SuggestionStatus) => {
                    setSuggestions((prev) =>
                      prev.map((x) => (x.id === s.id ? { ...x, status: next } : x)),
                    );
                  }}
                />
              ))}
            </div>
          </div>
        )}
      </section>
    </>
  );
}
