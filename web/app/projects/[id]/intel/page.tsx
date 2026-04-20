/**
 * /projects/[id]/intel — per-project intel view (Phase 10 Plan 12).
 *
 * Server component. Fetches project detail (parent layout.tsx already
 * validated access and would have redirected on 403/404) and delegates
 * rendering to the shared EventsClient with a `projectId` prop. The client
 * threads `project_id=<uuid>` into every `listEvents` call and — via the
 * nested EventDetailDrawer → AttackGraph chain — into every subsequent
 * `/api/events/:id/graph?project_id=X` request.
 *
 * URL shape note:
 *   - Filter params (`?tag=`, `?tlp=`, `?observed_from=`, etc) serialise to
 *     the query string as usual. `project_id` is intentionally NOT part of
 *     the query string — the pinning lives in the route segment itself, and
 *     EventsClient's buildSearchParams omits it (see EventsClient.tsx for the
 *     lock reasoning).
 *   - The `?event=<id>` drawer param works the same as on /events; the
 *     drawer's closeDrawer() returns to /projects/[id]/intel via the
 *     `basePath` prop passed from EventsClient.
 *
 * Phase 10 scope: no project-specific filter widgets beyond the pinned badge;
 * full custom widget grid (event-count-by-day sparkline, top tags, source
 * breakdown) lands in v2.1 per CONTEXT.md §Per-project intel + graph views.
 *
 * Access gating: layout.tsx already redirected on 403/404. A race condition
 * could leave a stale project visible here; re-fetch at the page level so the
 * error boundary catches any access revocation mid-session.
 */

import { Suspense } from "react";
import { fetchProjectDetail } from "../../lib/api";
import { EventsClient } from "@/app/events/EventsClient";

export const dynamic = "force-dynamic";

export default async function ProjectIntelPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const project = await fetchProjectDetail(id);
  return (
    <Suspense
      fallback={
        <div
          className="p-6 text-muted-foreground"
          data-testid="project-intel-loading"
        >
          Loading events…
        </div>
      }
    >
      <EventsClient projectId={project.id} projectName={project.name} />
    </Suspense>
  );
}
