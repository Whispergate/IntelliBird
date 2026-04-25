"use client";

/**
 * IngestSparkline — 120×32 Recharts BarChart sparkline for source ingest volume.
 * Phase 16 plan 16-07. MON-04 dashboard requirement.
 *
 * Props:
 *   data — up to 168 hourly buckets ({ bucket: string; total: number }[])
 *          Renders blue bars; empty/zero data shows a faint placeholder.
 *
 * Mirrors Phase 15 ScoreHistogram pattern (ResponsiveContainer + BarChart).
 * Width 120, height 32 per plan spec.
 */

import { BarChart, Bar, ResponsiveContainer } from "recharts";

export type SparklineBucket = {
  bucket: string;
  total: number;
};

export function IngestSparkline({ data }: { data: SparklineBucket[] }) {
  const hasData = data.length > 0 && data.some((d) => d.total > 0);

  if (!hasData) {
    return (
      <div
        style={{
          width: 120,
          height: 32,
          background: "rgba(96,165,250,0.08)",
          borderRadius: 2,
        }}
      />
    );
  }

  return (
    <div style={{ width: 120, height: 32 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
          <Bar
            dataKey="total"
            fill="#60a5fa"
            radius={[1, 1, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
