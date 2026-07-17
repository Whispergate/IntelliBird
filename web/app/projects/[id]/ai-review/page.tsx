/**
 * /projects/[id]/ai-review — AI Suggestion Queue page.
 * / UI-SPEC §Surface 2.
 *
 * Server component shell that hydrates the client AIReviewTable component.
 * Tab registered at position 18 in ProjectTabs.tsx.
 */

import { Suspense } from "react";
import { AIReviewTable } from "./AIReviewTable";

export default async function AIReviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
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
      <AIReviewTable projectId={id} />
    </Suspense>
  );
}
