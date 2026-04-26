/**
 * /projects/[id]/ai-review — AI Suggestion Queue page.
 * Phase 17 plan 17-08 / UI-SPEC §Surface 2.
 *
 * Server component shell that hydrates the client AIReviewTable component.
 * Tab registered at position 18 in ProjectTabs.tsx.
 */

import { Suspense } from "react";
import { AIReviewTable } from "./AIReviewTable";

export default function AIReviewPage({
  params,
}: {
  params: { id: string };
}) {
  return (
    <Suspense
      fallback={
        <div className="max-w-5xl mx-auto pt-6">
          <div className="animate-pulse space-y-4">
            <div className="h-8 bg-muted rounded w-48" />
            <div className="h-4 bg-muted rounded w-64" />
            <div className="h-10 bg-muted rounded w-full" />
            <div className="h-10 bg-muted rounded w-full" />
          </div>
        </div>
      }
    >
      <AIReviewTable projectId={params.id} />
    </Suspense>
  );
}
