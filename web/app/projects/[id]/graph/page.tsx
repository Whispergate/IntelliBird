/**
 * /projects/[id]/graph — per-project attack graph landing (Phase 10 Plan 12).
 *
 * Server component. Phase 10 ships an empty-state landing with a CTA back to
 * /projects/[id]/intel. Rationale per CONTEXT.md §Per-project intel + graph
 * views and 10-12-PLAN.md:
 *
 *   - AttackGraph is seeded from a specific event; it has no meaningful
 *     standalone render without an event-id input. Exposing a seed picker on
 *     the page would duplicate the events list that already lives on
 *     /projects/[id]/intel.
 *   - The operator flow is: drill into an event from the Intel view → open
 *     EventDetailDrawer → the nested AttackGraph renders for that event, with
 *     `projectId` threaded in automatically so every BFS hop filters to
 *     project-scoped events (H-3 closure).
 *   - The full project-level attack graph view (forced-layout unification of
 *     all project events' traversals) is a v2.1 enhancement.
 *
 * The Graph tab in ProjectTabs (plan 10-09) routes here; the route exists so
 * the tab does not 404. The page guides the operator back to Intel.
 */

import Link from "next/link";
import { fetchProjectDetail } from "../../lib/api";
import { Button } from "@/components/ui/button";

export const dynamic = "force-dynamic";

export default async function ProjectGraphPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  // layout.tsx already validated access — fetch again so the page can show
  // the project name in its CTA. A mid-session access revocation surfaces via
  // the Next.js error boundary, consistent with page.tsx for Overview.
  const project = await fetchProjectDetail(id);

  return (
    <div
      className="flex flex-col items-center justify-center py-16 gap-3 text-center"
      data-testid="project-graph-landing"
    >
      <h2
        className="brand-heading text-foreground"
        style={{ fontSize: 22, fontWeight: 500 }}
      >
        No graph for this project yet
      </h2>
      <p
        className="text-muted-foreground max-w-md"
        style={{ fontSize: 16, lineHeight: 1.7 }}
      >
        Ingest events matching the scope, then open an event from the Intel
        view to see its attack-graph traversal scoped to this project.
      </p>
      <Link
        href={`/projects/${project.id}/intel`}
        aria-label={`Open Intel view for ${project.name}`}
      >
        <Button
          style={{
            backgroundColor: "var(--brand-signal)",
            color: "var(--brand-ink)",
          }}
        >
          Open Intel view
        </Button>
      </Link>
    </div>
  );
}
