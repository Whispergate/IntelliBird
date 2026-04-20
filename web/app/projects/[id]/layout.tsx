/**
 * /projects/[id] — project detail layout (Phase 10 Plan 09).
 *
 * Server component. Fetches the project detail once via `fetchProjectDetail`
 * and wraps every nested route (Overview via page.tsx, Intel via ./intel/,
 * Graph via ./graph/) with the breadcrumb + sub-tab strip.
 *
 * Access gating: `fetchProjectDetail` throws on 403 or 404 (both shapes mean
 * "you don't see this project"). The catch branch redirects to
 * /projects?error=not_found — /projects reads that query param and surfaces a
 * sonner toast (wired in plan 10-08 ProjectsClient if needed; operator can
 * wire later).
 *
 * Notes:
 *   - Global TopNav stays — it comes from a route-local shell or a parent
 *     layout not managed here. See web/app/components/TopNav.tsx; this layout
 *     renders only the project-scoped breadcrumb + tab strip beneath it.
 *   - Next.js 15: params is a Promise — `await params` before reading `.id`.
 *   - Client components own the URL tab state (ProjectTabs) and the active
 *     section label (ProjectBreadcrumb). The layout stays server-rendered so
 *     the project fetch does not re-run on tab switch.
 */

import { redirect } from "next/navigation";
import { fetchProjectDetail, type ProjectResponse } from "../lib/api";
import { ProjectBreadcrumb } from "./ProjectBreadcrumb";
import { ProjectTabs } from "./ProjectTabs";

export const dynamic = "force-dynamic";

export default async function ProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let project: ProjectResponse;
  try {
    project = await fetchProjectDetail(id);
  } catch {
    // 403 + 404 both collapse to "project not visible". Operator will see a
    // generic list view with a toast wired in ProjectsClient (10-08 surface).
    redirect("/projects?error=not_found");
  }

  return (
    <div>
      <ProjectBreadcrumb projectName={project.name} />
      <ProjectTabs projectId={project.id} projectName={project.name} />
      <div className="mt-6">{children}</div>
    </div>
  );
}
