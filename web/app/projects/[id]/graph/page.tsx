/**
 * /projects/[id]/graph — Project-aggregate attack graph (Phase 20 Plan 20-03).
 *
 * Server Component. Fetches the project graph from
 * GET /api/projects/{id}/graph via _apiFetch (CLAUDE.md convention — server-side
 * fetches MUST inject Bearer token; never use raw fetch(${API_BASE}/...)).
 *
 * Passes data to the <ProjectGraph> client component which renders:
 *   - Cytoscape with built-in `cose` layout for populated projects
 *   - Empty-state cards for projects with no events or no graph relationships
 *   - Truncate banner when the API indicates result truncation
 */

import Link from "next/link";
import { fetchProjectGraph } from "@/app/projects/lib/api";
import { ProjectGraph } from "./ProjectGraph";
import { Button } from "@/components/ui/button";

export const dynamic = "force-dynamic";

export default async function ProjectGraphPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  try {
    const data = await fetchProjectGraph(id);
    return <ProjectGraph data={data} projectId={id} />;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const is403or404 =
      message.startsWith("403") ||
      message.startsWith("404") ||
      message.includes("Forbidden") ||
      message.includes("Not Found");

    return (
      <div
        role="alert"
        className="flex flex-col items-center justify-center py-16 gap-4 text-center"
      >
        <p className="text-muted-foreground">
          {is403or404
            ? "You do not have access to this project."
            : `Failed to load graph: ${message}`}
        </p>
        <Link href={`/projects/${id}`}>
          <Button variant="outline">Back to project</Button>
        </Link>
      </div>
    );
  }
}
