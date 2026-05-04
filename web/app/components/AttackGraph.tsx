"use client";

import dynamic from "next/dynamic";

export const AttackGraph = dynamic<{ eventId: string; height?: number; projectId?: string | null }>(
  () => import("./AttackGraphImpl").then((m) => m.AttackGraphImpl),
  {
    ssr: false,
    loading: () => (
      <div
        data-testid="attack-graph-dynamic-loading"
        className="animate-pulse bg-muted rounded"
        style={{ height: 240, width: "100%" }}
      />
    ),
  },
);
