/**
 * /projects/[id]/intel — per-project intel view.
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
 * scope: no project-specific filter widgets beyond the pinned badge
 * full custom widget grid (event-count-by-day sparkline, top tags, source
 * breakdown) lands in v2.1 per CONTEXT.md §Per-project intel + graph views.
 *
 * Access gating: layout.tsx already redirected on 403/404. A race condition
 * could leave a stale project visible here; re-fetch at the page level so the
 * error boundary catches any access revocation mid-session.
 */

import { Suspense } from "react";
import Link from "next/link";
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
    <div>
      <div className="flex items-center justify-end px-4 pt-3 pb-1">
        <Link
          href={`/projects/${id}/graph`}
          className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium"
          style={{ backgroundColor: "var(--brand-signal)", color: "var(--brand-ink)" }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3"/><circle cx="4" cy="6" r="2"/><circle cx="20" cy="6" r="2"/>
            <circle cx="4" cy="18" r="2"/><circle cx="20" cy="18" r="2"/>
            <line x1="6" y1="6" x2="10" y2="11"/><line x1="18" y1="6" x2="14" y2="11"/>
            <line x1="6" y1="18" x2="10" y2="13"/><line x1="18" y1="18" x2="14" y2="13"/>
          </svg>
          Analyse Attack Path
        </Link>
      </div>
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
    </div>
  );
}
