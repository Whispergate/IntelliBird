/**
 * /projects/[id]/iocs — (IOC Foundation UI).
 *
 * RSC wrapper that fetches the first page of active IOCs server-side via
 * `_apiFetch` (per CLAUDE.md SSR-fetch convention) and hands them to the
 * client component. Browser-side filter changes refetch via `_apiFetch`'s
 * relative-URL branch which traverses `/api/[...path]` route-handler proxy.
 */

import { _apiFetch, type IOCRead } from "@/app/api-client";
import { IOCsClient } from "./IOCsClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function IOCsPage({ params }: Props) {
  const { id: projectId } = await params;
  let initialRows: IOCRead[] = [];
  try {
    const res = await _apiFetch(
      `/api/iocs?project_id=${projectId}&status=active&limit=50`,
      { cache: "no-store" },
    );
    if (res.ok) {
      initialRows = (await res.json()) as IOCRead[];
    }
  } catch {
    initialRows = [];
  }
  return <IOCsClient projectId={projectId} initialRows={initialRows} />;
}
