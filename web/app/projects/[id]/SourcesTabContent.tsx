"use client";

/**
 * SourcesTabContent - Sources tab orchestrator for /projects/[id]
 * (PRJ-05).
 *
 * Thin wrapper over ProjectSourcesBinding. Kept as a separate named export so
 * ProjectDetailClient / page.tsx has a single "content per tab" symbol to
 * switch on, mirroring MembershipsTabContent.
 *
 * If later iterations introduce Sources-tab-local controls (e.g. a "bulk
 * import from CSV" affordance, a per-source polling-interval override) they
 * belong in this file - ProjectSourcesBinding is specifically the multi-select
 * widget and should not grow into a full page.
 */

import type { ProjectResponse } from "../lib/api";
import { ProjectSourcesBinding } from "./components/ProjectSourcesBinding";

export function SourcesTabContent({
  project,
}: {
  project: ProjectResponse;
}) {
  return <ProjectSourcesBinding project={project} />;
}
