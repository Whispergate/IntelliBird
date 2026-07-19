"use client";

/**
 * ProjectDetailClient
 *
 * Thin client dispatcher that reads `?tab=` via useSearchParams and renders
 * the matching tab pane. Keeps page.tsx a server component (fetches project
 * detail once via Next.js de-duping) while tab selection stays reactive to
 * URL changes without re-running the fetch.
 *
 * Tab mapping:
 *   - (no ?tab=)         → OverviewClient            (default)
 *   - ?tab=overview      → OverviewClient
 *   - ?tab=scope-<type>  → ScopeTabContent           (7 scope types)
 *   - ?tab=sources       → SourcesTabContent         (10-11 stub for now)
 *   - ?tab=memberships   → MembershipsTabContent     (10-11 stub for now)
 *   - ?tab=settings      → SettingsTabContent
 *
 * Intel + Graph tabs are handled by nested routes (/intel/page.tsx,
 * /graph/page.tsx) - they never reach this component because ProjectTabs uses
 * router.push to navigate there. If someone crafts a URL with
 * `?tab=intel` or `?tab=graph` manually, we fall back to Overview.
 *
 * Next.js 15 note: useSearchParams requires a Suspense boundary. The parent
 * layout.tsx is an async server component, so Next.js wraps this client
 * subtree automatically - no explicit <Suspense> needed (same pattern as
 * ProjectBreadcrumb + ProjectTabs, per plan 10-09 key-decisions).
 */

import { useSearchParams } from "next/navigation";

import type { ProjectResponse } from "../lib/api";
import { MembershipsTabContent } from "./MembershipsTabContent";
import { OverviewClient } from "./OverviewClient";
import { ScopeTabContent } from "./ScopeTabContent";
import { SettingsTabContent } from "./SettingsTabContent";
import { SourcesTabContent } from "./SourcesTabContent";

export function ProjectDetailClient({
  project,
}: {
  project: ProjectResponse;
}) {
  const sp = useSearchParams();
  const tab = sp.get("tab") ?? "overview";

  if (tab === "overview") return <OverviewClient project={project} />;
  if (tab.startsWith("scope-"))
    return <ScopeTabContent project={project} tabKey={tab} />;
  if (tab === "sources") return <SourcesTabContent project={project} />;
  if (tab === "memberships")
    return <MembershipsTabContent project={project} />;
  if (tab === "settings") return <SettingsTabContent project={project} />;

  // Unknown tab (or /intel, /graph if someone crafted the query param
  // manually): fall back to the default Overview surface.
  return <OverviewClient project={project} />;
}
