/**
 * /projects/[id] - server component page that dispatches to the correct tab
 * pane based on the `?tab=` query param.
 *
 * History:
 *   - Plan 10-09 landed the layout.tsx access gate + ProjectBreadcrumb +
 *     ProjectTabs strip + OverviewClient. At that time page.tsx only rendered
 *     OverviewClient; other ?tab= values still landed on the Overview pane.
 *   - Plan 10-10 (THIS PLAN) extends page.tsx to dispatch via
 *     ProjectDetailClient - a thin client wrapper that reads `?tab=` via
 *     useSearchParams and picks the matching tab pane. This keeps page.tsx
 *     a server component (fetches project detail once) while the tab selection
 *     stays reactive to URL changes without a re-fetch.
 *   - Plan 10-11 will replace the MembershipsTabContent + SourcesTabContent
 *     stubs with real implementations.
 *   - Plan 10-12 owns the Intel + Graph nested routes; those don't go through
 *     page.tsx (they have their own /intel/page.tsx + /graph/page.tsx).
 *
 * Next.js 15: params is a Promise - await before reading `.id`. layout.tsx
 * already validated access; a refetch failure here propagates to the Next
 * error boundary.
 */

import { fetchProjectDetail } from "../lib/api";
import { ProjectDetailClient } from "./ProjectDetailClient";

export default async function ProjectOverviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const project = await fetchProjectDetail(id);
  return <ProjectDetailClient project={project} />;
}
