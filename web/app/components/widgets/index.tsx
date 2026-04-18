"use client";

import { IncomingIOCs } from "./IncomingIOCs";
import { CveRelevance } from "./CveRelevance";
import { VendorAdvisories } from "./VendorAdvisories";
import { ActorInfra } from "./ActorInfra";
import { FreshExploits } from "./FreshExploits";
import { ToolingChatter } from "./ToolingChatter";

const GRID_CLASS = "grid grid-cols-1 md:grid-cols-3 gap-6";

export function BlueWidgets() {
  return (
    <div data-testid="blue-widgets" className={GRID_CLASS}>
      <IncomingIOCs />
      <CveRelevance />
      <VendorAdvisories />
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
