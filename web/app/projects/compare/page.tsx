/**
 * /projects/compare — two-project comparison surface (Phase 10 Plan 13, PRJ-06).
 *
 * Server component: server-fetches the non-archived project list so the
 * client-side picker Selects have their options populated on first paint
 * (no separate round-trip). When the backend is unreachable the fetch fails
 * soft — the picker simply shows no options and the user can retry by
 * navigating back.
 *
 * The query-param parsing (?a=<uuid>&b=<uuid>) and the compareProjects fetch
 * happen on the client (ProjectCompareClient) because URL params must drive
 * useEffect + router.replace for the Swap / set-side actions.
 *
 * Middleware protection:
 *   web/proxy.ts matcher is extended to cover /projects/:path* so an
 *   unauthenticated request to /projects/compare redirects to /login?next=…
 *   before this server component runs.
 */

import { listProjects, type ProjectResponse } from "../lib/api";
import { ProjectCompareClient } from "./ProjectCompareClient";

export const dynamic = "force-dynamic";

export default async function ProjectComparePage() {
  let projects: ProjectResponse[] = [];
  try {
    projects = await listProjects({ includeArchived: false });
  } catch {
    projects = [];
  }
  return <ProjectCompareClient projects={projects} />;
}
