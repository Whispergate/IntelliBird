/**
 * /projects — Projects list page.
 *
 * Server component: fetches the initial non-archived project list via the
 * `listProjects` helper so the first paint has rows + legacy-sentinel visible
 * without a client round-trip. All interactivity (filters, create/edit
 * dialog, archive/restore, toasts, row navigation) lives in ProjectsClient.
 *
 * Error handling matches /sources: on fetch failure, fall back to an empty
 * array. ProjectsClient shows the "No projects yet" empty state, and the
 * operator can retry by toggling "Show archived" (which re-issues the fetch).
 */

import { listProjects, type ProjectResponse } from "./lib/api";
import { ProjectsClient } from "./ProjectsClient";

export const dynamic = "force-dynamic";

export default async function ProjectsPage() {
  let initialProjects: ProjectResponse[] = [];
  try {
    initialProjects = await listProjects({ includeArchived: false });
  } catch {
    initialProjects = [];
  }
  return <ProjectsClient initialProjects={initialProjects} />;
}
