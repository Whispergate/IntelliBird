/**
 * /projects/[id] - project detail layout.
 *
 * Server component. Fetches the project detail once via `fetchProjectDetail`
 * and wraps every nested route (Overview via page.tsx, Intel via ./intel/,
 * Graph via ./graph/) with the breadcrumb + sub-tab strip.
 *
 * (UX-02): derives the current user's per-project role via
 * `listMemberships` and passes it to `<ProjectRoleProvider>` so all descendant
 * client components can call `useProjectRole()` without individual API calls.
 *
 * Role derivation:
 *   1. Global Admin (session.user.role === "Admin") → role="Admin" (no API call needed)
 *   2. Else: call listMemberships(id), find membership where user_sub matches
 *      session.user.id, extract project_role. Null on miss or error (least-privilege).
 *
 * RESEARCH §5 key finding: auth.ts session callback does NOT forward the `pm` JWT
 * claim into the Next.js session object - `auth()` alone cannot read pm[project_id].
 * The listMemberships API call is the correct solution (Option A from RESEARCH §5).
 *
 * Access gating: `fetchProjectDetail` throws on 403 or 404 (both shapes mean
 * "you don't see this project"). The catch branch redirects to
 * /projects?error=not_found - /projects reads that query param and surfaces a
 * sonner toast (wired in plan 10-08 ProjectsClient if needed; operator can
 * wire later).
 *
 * Notes:
 *   - Global TopNav stays - it comes from a route-local shell or a parent
 *     layout not managed here. See web/app/components/TopNav.tsx; this layout
 *     renders only the project-scoped breadcrumb + tab strip beneath it.
 *   - Next.js 15: params is a Promise - `await params` before reading `.id`.
 *   - Client components own the URL tab state (ProjectTabs) and the active
 *     section label (ProjectBreadcrumb). The layout stays server-rendered so
 *     the project fetch does not re-run on tab switch.
 */

import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { fetchProjectDetail, listMemberships, type ProjectResponse } from "../lib/api";
import { ProjectBreadcrumb } from "./ProjectBreadcrumb";
import { ProjectTabs } from "./ProjectTabs";
import {
  ProjectRoleProvider,
  type ProjectRoleString,
} from "./ProjectRoleProvider";

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

  // Derive per-project role for ProjectRoleProvider.
  // RESEARCH §5: pm claim is NOT in session - must call listMemberships API.
  let role: ProjectRoleString = null;
  try {
    const session = await auth();
    if (session?.user) {
      const globalRole = (session.user as { role?: string }).role;
      if (globalRole === "Admin") {
        // Global Admin bypasses project membership - same logic as backend require_project_membership
        role = "Admin";
      } else {
        const userId = (session.user as { id?: string }).id;
        if (userId) {
          const memberships = await listMemberships(id);
          const mine = memberships.find((m) => m.user_sub === userId);
          role = (mine?.project_role as ProjectRoleString) ?? null;
        }
      }
    }
  } catch {
    // 403 from listMemberships (non-member), network error, or auth error.
    // Fall through to null (least-privilege: hide privileged actions).
    role = null;
  }

  return (
    <ProjectRoleProvider role={role}>
      <div className="w-full min-w-0 max-w-full">
        <ProjectBreadcrumb projectName={project.name} />
        <ProjectTabs projectId={project.id} projectName={project.name} />
        <div className="mt-6 min-w-0">{children}</div>
      </div>
    </ProjectRoleProvider>
  );
}
