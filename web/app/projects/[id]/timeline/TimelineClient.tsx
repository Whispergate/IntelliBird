"use client";

import { useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getTimelineSeries,
  getTimelineHeatmap,
  type TimelineSeriesResponse,
  type TimelineHeatmapResponse,
  type HeatmapCell,
} from "@/app/api-client";

const COLORS = [
  "#3b82f6",
  "#ef4444",
  "#f97316",
  "#eab308",
  "#10b981",
  "#6366f1",
  "#ec4899",
  "#14b8a6",
  "#f59e0b",
  "#8b5cf6",
];

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface TimelineAreaChartProps {
  series: TimelineSeriesResponse;
}

function TimelineAreaChart({ series }: TimelineAreaChartProps) {
  const tags = series.tags.slice(0, 10);

  // Flatten buckets to recharts-compatible flat objects: { ts, [tag]: count, ... }
  const data = series.buckets.map((bucket) => {
    const row: Record<string, string | number> = { ts: bucket.ts };
    for (const tag of tags) {
      row[tag] = bucket.counts_by_tag[tag] ?? 0;
    }
    return row;
  });

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center" style={{ height: 280 }}>
        <p className="text-muted-foreground text-sm">No events in this range.</p>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
        <XAxis
          dataKey="ts"
          tick={{ fontSize: 10 }}
          tickFormatter={(v: string) => {
            const d = new Date(v);
            return `${d.getMonth() + 1}/${d.getDate()}`;
          }}
        />
        <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
        <Tooltip />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {tags.map((tag, i) => (
          <Area
            key={tag}
            type="monotone"
            dataKey={tag}
            stackId="1"
            stroke={COLORS[i % COLORS.length]}
            fill={COLORS[i % COLORS.length]}
            fillOpacity={0.4}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

interface ActivityHeatmapProps {
  heatmap: TimelineHeatmapResponse;
}

function cellColorClass(count: number, maxCount: number): string {
  if (maxCount === 0 || count === 0) return "bg-muted";
  const ratio = count / maxCount;
  if (ratio < 0.2) return "bg-blue-100";
  if (ratio < 0.4) return "bg-blue-200";
  if (ratio < 0.6) return "bg-blue-400";
  if (ratio < 0.8) return "bg-blue-600";
  return "bg-blue-700";
}

function ActivityHeatmap({ heatmap }: ActivityHeatmapProps) {
  const maxCount = Math.max(...heatmap.cells.map((c) => c.count), 0);

  // Build a lookup map for O(1) access
  const cellMap = new Map<string, HeatmapCell>();
  for (const cell of heatmap.cells) {
    cellMap.set(`${cell.hour}-${cell.dow}`, cell);
  }

  return (
    <div className="overflow-x-auto">
      {/* Header row: DOW labels */}
      <div className="grid grid-cols-7 gap-px mb-1 min-w-[196px]">
        {DOW_LABELS.map((d) => (
          <div key={d} className="text-center text-xs text-muted-foreground font-medium">
            {d}
          </div>
        ))}
      </div>
      {/* 24 hour rows × 7 day columns */}
      {Array.from({ length: 24 }, (_, hour) => (
        <div key={hour} className="grid grid-cols-7 gap-px mb-px min-w-[196px]">
          {Array.from({ length: 7 }, (_, dow) => {
            const cell = cellMap.get(`${hour}-${dow}`);
            const count = cell?.count ?? 0;
            const colorClass = cellColorClass(count, maxCount);
            return (
              <div
                key={dow}
                className={`h-3 w-full rounded-sm ${colorClass}`}
                title={`${hour}:00 ${DOW_LABELS[dow]} — ${count} events`}
              />
            );
          })}
        </div>
      ))}
      {/* Hour axis labels at bottom */}
      <div className="flex justify-between mt-1 min-w-[196px] px-px">
        <span className="text-xs text-muted-foreground">00:00</span>
        <span className="text-xs text-muted-foreground">12:00</span>
        <span className="text-xs text-muted-foreground">23:00</span>
      </div>
    </div>
  );
}

interface TimelineClientProps {
  projectId: string;
  initialSeries: TimelineSeriesResponse;
  initialHeatmap: TimelineHeatmapResponse;
  initialRangeDays: number;
}

const RANGE_OPTIONS = [7, 30, 90] as const;

export default function TimelineClient({
  projectId,
  initialSeries,
  initialHeatmap,
  initialRangeDays,
}: TimelineClientProps) {
  const [rangeDays, setRangeDays] = useState<number>(initialRangeDays);
  const [series, setSeries] = useState<TimelineSeriesResponse>(initialSeries);
  const [heatmap, setHeatmap] = useState<TimelineHeatmapResponse>(initialHeatmap);
  const [loading, setLoading] = useState(false);

  async function handleRangeChange(days: number) {
    if (days === rangeDays) return;
    setLoading(true);
    setRangeDays(days);
    try {
      const [newSeries, newHeatmap] = await Promise.all([
        getTimelineSeries(projectId, days),
        getTimelineHeatmap(projectId, days),
      ]);
      setSeries(newSeries);
      setHeatmap(newHeatmap);
    } catch {
      // Keep existing data on error
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6 space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <CardTitle>Pattern-of-Life Timeline</CardTitle>
            {/* Range picker */}
            <div className="flex gap-2">
              {RANGE_OPTIONS.map((days) => (
                <Button
                  key={days}
                  variant="outline"
                  size="sm"
                  aria-pressed={rangeDays === days}
                  className={
                    rangeDays === days
                      ? "border-[var(--brand-signal)] text-foreground"
                      : "text-muted-foreground"
                  }
                  onClick={() => handleRangeChange(days)}
                  disabled={loading}
                >
                  {days}d
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Stacked area chart — 2/3 width on large screens */}
            <div className="lg:col-span-2">
              <p className="text-sm font-medium text-muted-foreground mb-2">
                Event Volume by Tag
              </p>
              <TimelineAreaChart series={series} />
            </div>
            {/* Heatmap — 1/3 width on large screens */}
            <div>
              <p className="text-sm font-medium text-muted-foreground mb-2">
                Activity Heatmap (hour × day)
              </p>
              <ActivityHeatmap heatmap={heatmap} />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
