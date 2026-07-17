"use client";

/**
 * ScoringTabContent — Admin scoring config page for /projects/[id]/scoring.
 * UI-SPEC §Surface 4.
 *
 * Four cards:
 *   Card 1 — Score Weights (4 number inputs + decay half-life + Save weights button)
 *   Card 2 — Tier Cutoffs (4 number inputs S/A/B/C + validation)
 *   Card 3 — Score Histogram (recharts BarChart, 10 buckets, coloured by tier)
 *   Card 4 — Rescore Status (last rescored + progress + Trigger rescore button)
 *
 * API contracts (from plan 15-07):
 *   GET  /api/projects/{id}/scoring        → ScoringRulesRead
 *   PUT  /api/projects/{id}/scoring        body ScoringRulesPayload → ScoringRulesRead
 *   POST /api/projects/{id}/rescore        → 202 { queued: true, project_id }
 *   GET  /api/projects/{id}/rescore/status → { last_rescore_at, in_progress_count, total_count }
 *
 * Histogram data: v1 client-side aggregation from /api/events?project_id={id}&limit=500.
 * A dedicated /api/projects/{id}/score-histogram backend endpoint is a backlog item.
 *
 * Toast: sonner (matches existing SettingsTabContent.tsx pattern).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScoreHistogram, type HistogramBucket } from "./components/ScoreHistogram";
import { AIRerankCard } from "./AIRerankCard";

// ---------------------------------------------------------------------------
// Types matching backend schemas/scoring.py
// ---------------------------------------------------------------------------

interface ScoringWeights {
  cvss: number;
  recency: number;
  source: number;
  relevance: number;
}

interface TierCutoffs {
  S: number;
  A: number;
  B: number;
  C: number;
}

interface ScoringRulesRead {
  project_id: string;
  version: number;
  rules: {
    weights: ScoringWeights;
    decay_half_life_days: number;
    tier_cutoffs: TierCutoffs;
  };
  is_default: boolean;
}

interface RescoreStatus {
  last_rescore_at: string | null;
  in_progress_count: number;
  total_count: number;
}

// ---------------------------------------------------------------------------
// Defaults (mirror backend DEFAULT_SCORING_CONFIG)
// ---------------------------------------------------------------------------

const DEFAULT_WEIGHTS: ScoringWeights = { cvss: 50, recency: 20, source: 15, relevance: 15 };
const DEFAULT_TIER_CUTOFFS: TierCutoffs = { S: 90, A: 75, B: 55, C: 30 };
const DEFAULT_DECAY = 14;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Relative time string. */
function relativeTime(iso: string | null): string {
  if (!iso) return "Never rescored";
  const diffMs = Date.now() - Date.parse(iso);
  if (diffMs < 0) return "just now";
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

/**
 * Build 10-bucket histogram data from a list of scores.
 *
 * Bucket → tier assignment (for histogram bar colouring, midpoint-based):
 *   90-100 → S  (midpoint ~95)
 *   80-89  → A  (midpoint ~85)
 *   70-79  → A  (midpoint ~75, straddles A/B cutoff — assign A for histogram simplicity)
 *   60-69  → B  (midpoint ~65)
 *   50-59  → B  (midpoint ~55, straddles B/C cutoff — assign B for histogram simplicity)
 *   40-49  → C  (midpoint ~45)
 *   30-39  → C  (midpoint ~35)
 *   20-29  → D
 *   10-19  → D
 *   0-9    → D
 *
 * v1: client-side aggregation. Backend endpoint is a backlog item.
 */
function buildBuckets(scores: (number | null)[]): HistogramBucket[] {
  const TIER_MAP: Array<HistogramBucket["tier"]> = [
    "D", "D", "D", "C", "C", "B", "B", "A", "A", "S",
  ];
  const buckets: HistogramBucket[] = Array.from({ length: 10 }, (_, i) => ({
    bucket: i === 9 ? "90-100" : `${i * 10}-${i * 10 + 9}`,
    count: 0,
    tier: TIER_MAP[i],
  }));
  for (const s of scores) {
    if (s == null) continue;
    const idx = Math.min(9, Math.floor(s / 10));
    buckets[idx].count++;
  }
  return buckets;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ScoringTabContent({
  projectId,
  aiRerankEnabled = false,
}: {
  projectId: string;
  aiRerankEnabled?: boolean;
}) {
  // ---- Form state ----
  const [weights, setWeights] = useState<ScoringWeights>(DEFAULT_WEIGHTS);
  const [decayDays, setDecayDays] = useState<number>(DEFAULT_DECAY);
  const [tierCutoffs, setTierCutoffs] = useState<TierCutoffs>(DEFAULT_TIER_CUTOFFS);

  // ---- Rescore status ----
  const [rescoreStatus, setRescoreStatus] = useState<RescoreStatus | null>(null);
  const [polling, setPolling] = useState(false);
  const wasPollingActive = useRef(false); // tracks if in_progress_count was > 0
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---- Histogram ----
  const [histogramData, setHistogramData] = useState<HistogramBucket[]>(buildBuckets([]));

  // ---- Save state ----
  const [saving, setSaving] = useState(false);

  // ---- Validation ----
  const weightSum = weights.cvss + weights.recency + weights.source + weights.relevance;
  const weightsValid = Math.abs(weightSum - 100) < 0.001;
  const cutoffsValid =
    tierCutoffs.S > tierCutoffs.A &&
    tierCutoffs.A > tierCutoffs.B &&
    tierCutoffs.B > tierCutoffs.C &&
    tierCutoffs.C > 0;
  const canSave = weightsValid && cutoffsValid;

  // ---------------------------------------------------------------------------
  // API helpers
  // ---------------------------------------------------------------------------

  const fetchScoringRules = useCallback(async () => {
    try {
      const res = await fetch(`/api/projects/${projectId}/scoring`, {
        credentials: "include",
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        toast.error(`Could not load scoring config. ${text || "Check your connection and refresh."}`);
        return;
      }
      const data: ScoringRulesRead = await res.json();
      setWeights(data.rules.weights);
      setDecayDays(data.rules.decay_half_life_days);
      setTierCutoffs(data.rules.tier_cutoffs);
    } catch {
      toast.error("Could not load scoring config. Check your connection and refresh.");
    }
  }, [projectId]);

  const fetchRescoreStatus = useCallback(async (): Promise<RescoreStatus | null> => {
    try {
      const res = await fetch(`/api/projects/${projectId}/rescore/status`, {
        credentials: "include",
      });
      if (!res.ok) return null;
      return (await res.json()) as RescoreStatus;
    } catch {
      return null;
    }
  }, [projectId]);

  const fetchHistogramData = useCallback(async () => {
    try {
      // v1 client-side aggregation from events list.
      // Backend /api/projects/{id}/score-histogram endpoint is a backlog item.
      const res = await fetch(
        `/api/events?project_id=${projectId}&limit=500`,
        { credentials: "include" },
      );
      if (!res.ok) return;
      const data = await res.json();
      // Events list returns { items: EventResponse[] } or similar — extract scores
      const items: Array<{ score?: number | null }> = Array.isArray(data)
        ? data
        : (data.items ?? data.events ?? []);
      const scores = items.map((e) => e.score ?? null);
      setHistogramData(buildBuckets(scores));
    } catch {
      // Non-fatal — histogram stays empty
    }
  }, [projectId]);

  // ---------------------------------------------------------------------------
  // Polling lifecycle
  // ---------------------------------------------------------------------------

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    setPolling(false);
    wasPollingActive.current = false;
  }, []);

  const startPolling = useCallback(() => {
    // Clear any existing interval before starting a new one
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    setPolling(true);
    pollIntervalRef.current = setInterval(async () => {
      const status = await fetchRescoreStatus();
      if (!status) {
        stopPolling();
        toast.error("Rescore status check failed.");
        return;
      }
      setRescoreStatus(status);
      if (status.in_progress_count > 0) {
        wasPollingActive.current = true;
      } else if (wasPollingActive.current) {
        // Was > 0, now 0 → rescore complete
        stopPolling();
        toast.success(`Rescore complete — ${status.total_count} events updated.`);
        fetchHistogramData();
      }
    }, 3000);
  }, [fetchRescoreStatus, stopPolling, fetchHistogramData]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Initial mount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    fetchScoringRules();
    fetchRescoreStatus().then((status) => {
      if (status) setRescoreStatus(status);
    });
    fetchHistogramData();
  }, [fetchScoringRules, fetchRescoreStatus, fetchHistogramData]);

  // ---------------------------------------------------------------------------
  // Save handler
  // ---------------------------------------------------------------------------

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    try {
      const payload = {
        weights,
        decay_half_life_days: decayDays,
        tier_cutoffs: tierCutoffs,
      };
      const res = await fetch(`/api/projects/${projectId}/scoring`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let msg = "Unknown error.";
        try {
          const errData = await res.json();
          msg = errData.detail ?? errData.message ?? msg;
        } catch {
          msg = await res.text().catch(() => msg);
        }
        toast.error(`Could not save scoring rules. ${msg}`);
        return;
      }
      const saved: ScoringRulesRead = await res.json();
      toast.success(
        `Scoring rules saved. Rescore queued for ${rescoreStatus?.total_count ?? saved.version ?? 0} events.`,
      );
      // Backend auto-enqueues rescore on save — start polling immediately
      startPolling();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not save scoring rules. ${msg}`);
    } finally {
      setSaving(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Trigger rescore handler
  // ---------------------------------------------------------------------------

  async function handleTriggerRescore() {
    try {
      const res = await fetch(`/api/projects/${projectId}/rescore`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => "Unknown error.");
        toast.error(`Could not trigger rescore. ${msg}`);
        return;
      }
      toast.success("Rescore queued.");
      startPolling();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not trigger rescore. ${msg}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Weight field helper
  // ---------------------------------------------------------------------------

  function handleWeightChange(field: keyof ScoringWeights, value: string) {
    const parsed = parseFloat(value);
    setWeights((prev) => ({
      ...prev,
      [field]: isNaN(parsed) ? 0 : parsed,
    }));
  }

  function handleCutoffChange(field: keyof TierCutoffs, value: string) {
    const parsed = parseFloat(value);
    setTierCutoffs((prev) => ({
      ...prev,
      [field]: isNaN(parsed) ? 0 : parsed,
    }));
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="max-w-2xl mx-auto pt-6 space-y-8">

      {/* ------------------------------------------------------------------ */}
      {/* Card 1 — Score Weights                                              */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="brand-heading">Score Weights</CardTitle>
          <p className="text-muted-foreground text-sm mt-1">
            Weights must sum to 100. Changes trigger a project rescore.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <Label htmlFor="weight-cvss">CVSS weight</Label>
              <Input
                id="weight-cvss"
                type="number"
                min={0}
                max={100}
                step={1}
                value={weights.cvss}
                onChange={(e) => handleWeightChange("cvss", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="weight-recency">Recency weight</Label>
              <Input
                id="weight-recency"
                type="number"
                min={0}
                max={100}
                step={1}
                value={weights.recency}
                onChange={(e) => handleWeightChange("recency", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="weight-source">Source confidence weight</Label>
              <Input
                id="weight-source"
                type="number"
                min={0}
                max={100}
                step={1}
                value={weights.source}
                onChange={(e) => handleWeightChange("source", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="weight-relevance">Relevance weight</Label>
              <Input
                id="weight-relevance"
                type="number"
                min={0}
                max={100}
                step={1}
                value={weights.relevance}
                onChange={(e) => handleWeightChange("relevance", e.target.value)}
              />
            </div>
          </div>

          {!weightsValid && (
            <p className="text-xs text-destructive mt-2">
              Weights must sum to 100 — current total: {weightSum}
            </p>
          )}

          <div className="mt-4">
            <Label htmlFor="decay-days">Decay half-life (days)</Label>
            <Input
              id="decay-days"
              type="number"
              min={1}
              max={365}
              value={decayDays}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                setDecayDays(isNaN(v) ? DEFAULT_DECAY : v);
              }}
            />
          </div>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Card 2 — Tier Cutoffs                                               */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="brand-heading">Tier Cutoffs</CardTitle>
          <p className="text-muted-foreground text-sm mt-1">
            Score thresholds for S/A/B/C tiers. D tier is everything below C.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <Label htmlFor="cutoff-s">S threshold (≥)</Label>
              <Input
                id="cutoff-s"
                type="number"
                min={0}
                max={100}
                step={1}
                value={tierCutoffs.S}
                onChange={(e) => handleCutoffChange("S", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="cutoff-a">A threshold (≥)</Label>
              <Input
                id="cutoff-a"
                type="number"
                min={0}
                max={100}
                step={1}
                value={tierCutoffs.A}
                onChange={(e) => handleCutoffChange("A", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="cutoff-b">B threshold (≥)</Label>
              <Input
                id="cutoff-b"
                type="number"
                min={0}
                max={100}
                step={1}
                value={tierCutoffs.B}
                onChange={(e) => handleCutoffChange("B", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="cutoff-c">C threshold (≥)</Label>
              <Input
                id="cutoff-c"
                type="number"
                min={0}
                max={100}
                step={1}
                value={tierCutoffs.C}
                onChange={(e) => handleCutoffChange("C", e.target.value)}
              />
            </div>
          </div>

          {!cutoffsValid && (
            <p className="text-xs text-destructive mt-2">
              Thresholds must be strictly descending: S &gt; A &gt; B &gt; C &gt; 0
            </p>
          )}

          <div className="flex justify-end mt-6">
            <Button
              onClick={handleSave}
              disabled={!canSave || saving}
            >
              {saving ? "Saving…" : "Save weights"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Card 3 — Score Distribution (histogram)                             */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="brand-heading">Score Distribution</CardTitle>
          <p className="text-muted-foreground text-sm mt-1">
            Distribution of current event scores for this project.
          </p>
        </CardHeader>
        <CardContent>
          <ScoreHistogram data={histogramData} />
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Card 4 — Rescore Status                                             */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="brand-heading">Rescore Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-4">
              <span className="text-sm text-muted-foreground">
                Last rescored {relativeTime(rescoreStatus?.last_rescore_at ?? null)}
              </span>
              {polling && rescoreStatus && rescoreStatus.in_progress_count > 0 && (
                <span className="text-sm text-foreground flex items-center gap-1">
                  <span className="animate-pulse">●</span>
                  Rescoring… {rescoreStatus.total_count - rescoreStatus.in_progress_count} /{" "}
                  {rescoreStatus.total_count}
                </span>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleTriggerRescore}
              disabled={polling}
            >
              Trigger rescore
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Card 5 — AI Re-ranking (only when ai_rerank_enabled)                */}
      {/* ------------------------------------------------------------------ */}
      <AIRerankCard projectId={projectId} aiRerankEnabled={aiRerankEnabled} />

    </div>
  );
}
