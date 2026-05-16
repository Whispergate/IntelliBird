"use client";

import { IncomingIOCs } from "./IncomingIOCs";
import { CveRelevance } from "./CveRelevance";
import { VendorAdvisories } from "./VendorAdvisories";
import { ActorInfra } from "./ActorInfra";
import { FreshExploits } from "./FreshExploits";
import { ToolingChatter } from "./ToolingChatter";
import InfluenceOpsWidget from "@/app/projects/[id]/InfluenceOpsWidget";

const GRID_CLASS = "grid grid-cols-1 md:grid-cols-3 gap-6";

// InfluenceOpsWidget is hidden at this level (no project context).
// Live rendering is in OverviewClient — it queries per-project source counts.
export function BlueWidgets() {
  return (
    <div data-testid="blue-widgets" className={GRID_CLASS}>
      <IncomingIOCs />
      <CveRelevance />
      <VendorAdvisories />
      <InfluenceOpsWidget socialSourceCount={0} clusters={[]} />
    </div>
  );
}

export function RedWidgets() {
  return (
    <div data-testid="red-widgets" className={GRID_CLASS}>
      <ActorInfra />
      <FreshExploits />
      <ToolingChatter />
    </div>
  );
}
