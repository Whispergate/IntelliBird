/**
 * DISINFO-04 — InfluenceOpsWidget renders null when no social sources exist,
 *              shows a heading when sources are present, and lists CIB clusters.
 *
 * Implemented in: web/app/projects/[id]/InfluenceOpsWidget.tsx
 *
 * Will fail with "Cannot find module './InfluenceOpsWidget'" until Plan 06 ships.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

// Direct import — will fail until Plan 06 creates the component
import InfluenceOpsWidget from "./InfluenceOpsWidget";

interface CibCluster {
  id: string;
  detected_at: string;
  member_count: number;
  severity: "medium" | "high";
}

describe("InfluenceOpsWidget", () => {
  it("renders_null_when_no_social_sources", () => {
    /**
     * When socialSourceCount is 0, the widget must render nothing —
     * no DOM nodes should be present in the container.
     */
    const { container } = render(
      <InfluenceOpsWidget socialSourceCount={0} clusters={[]} />
    );
    // Widget must be empty / null when there are no social sources configured
    expect(container.firstChild).toBeNull();
  });

  it("renders_widget_when_social_sources_present", () => {
    /**
     * When socialSourceCount >= 1, the widget renders its heading
     * "Influence Operations" and the cluster panel.
     */
    render(
      <InfluenceOpsWidget socialSourceCount={1} clusters={[]} />
    );
    expect(screen.getByText(/influence operations/i)).toBeDefined();
  });

  it("renders_cluster_list", () => {
    /**
     * When 2 CIB clusters are provided, the widget renders 2 cluster rows.
     * Each row is identifiable by the cluster id rendered somewhere in it.
     */
    const clusters: CibCluster[] = [
      {
        id: "cluster-001",
        detected_at: "2025-03-15T08:00:00Z",
        member_count: 12,
        severity: "high",
      },
      {
        id: "cluster-002",
        detected_at: "2025-03-15T09:30:00Z",
        member_count: 7,
        severity: "medium",
      },
    ];

    render(
      <InfluenceOpsWidget socialSourceCount={2} clusters={clusters} />
    );

    // Both cluster ids must appear somewhere in the rendered output
    expect(screen.getByText(/cluster-001/i)).toBeDefined();
    expect(screen.getByText(/cluster-002/i)).toBeDefined();
  });
});
