"use client";

/**
 * ScoreHistogram — Recharts BarChart wrapper for the Score Distribution card.
 * UI-SPEC §Surface 4 Card 3.
 *
 * Props:
 *   data — 10 pre-bucketed HistogramBucket entries (built by ScoringTabContent)
 *
 * Buckets: "0-9", "10-19", ..., "90-100" (10 items total).
 * Bar colour: per-tier using hex colours that match the UI-SPEC tier badge palette.
 *
 * Empty state: rendered when sum of all bucket counts is 0 (no scored events).
 *
 * Height: 160px (UI-SPEC §Surface 4 §Card 3 — Score Histogram).
 */

import { BarChart, Bar, Cell, XAxis, YAxis, ResponsiveContainer, Tooltip } from "recharts";

export type HistogramBucket = {
  bucket: string;
  count: number;
  tier: "S" | "A" | "B" | "C" | "D";
};

// Hex values matching the UI-SPEC tier badge colour map (Tailwind colour stops):
//   S → red-500     (#ef4444)
//   A → orange-500  (#f97316)
//   B → yellow-500  (#eab308)
//   C → blue-500    (#3b82f6)
//   D → muted       (#6b7280 — gray-500 approximation)
const TIER_HEX: Record<HistogramBucket["tier"], string> = {
  S: "#ef4444",
  A: "#f97316",
  B: "#eab308",
  C: "#3b82f6",
  D: "#6b7280",
};

export function ScoreHistogram({ data }: { data: HistogramBucket[] }) {
  const total = data.reduce((acc, b) => acc + b.count, 0);

  if (total === 0) {
    return (
      <div
        className="flex items-center justify-center"
        style={{ height: 160 }}
      >
        <p className="text-muted-foreground text-sm text-center">
          No scored events yet. Events will appear here after the first rescore.
        </p>
      </div>
    );
  }

  return (
    <div style={{ width: "100%", height: 160 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
          <XAxis
            dataKey="bucket"
            tick={{ fontSize: 10 }}
            interval={0}
            angle={-30}
            textAnchor="end"
            height={36}
          />
          <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
          <Tooltip
            formatter={(value: number) => [value, "Events"]}
            labelFormatter={(label: string) => `Score ${label}`}
          />
          <Bar dataKey="count" radius={[2, 2, 0, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={TIER_HEX[d.tier]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
