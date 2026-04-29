/**
 * /projects/[id]/brand/stoplist — Per-project brand stoplist page (Phase 21 / BRAND-01).
 *
 * Server Component. Fetches the stoplist server-side via `listBrandStoplist`
 * (which uses `_apiFetch` → Auth.js v5 bearer injection). Hands `initialTerms`
 * to `StoplistClient` for interactive rendering.
 *
 * Convention: server-side fetches MUST use `_apiFetch` (web/app/projects/lib/api.ts)
 * so the Auth.js session bearer is injected. Direct `fetch(http://api:8000/...)`
 * calls return 401 under AUTH_ENABLED=true.
 */

import { listBrandStoplist } from "@/app/projects/lib/api";
import { StoplistClient } from "./StoplistClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function StoplistPage({ params }: Props) {
  const { id } = await params;

  let initialTerms: Awaited<ReturnType<typeof listBrandStoplist>> = [];
  let fetchError: string | null = null;

  try {
    initialTerms = await listBrandStoplist(id);
  } catch (err) {
    fetchError = err instanceof Error ? err.message : "Could not load stoplist.";
  }

  if (fetchError) {
    return (
      <div className="flex items-center gap-3 py-6 text-destructive text-sm">
        <span>Could not load stoplist. {fetchError}</span>
      </div>
    );
  }

  return <StoplistClient projectId={id} initialTerms={initialTerms} />;
}
