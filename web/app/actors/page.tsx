/**
 * /actors — (Threat Actors UI).
 *
 * RSC wrapper that fetches the first page of actors server-side via
 * `_apiFetch` (per CLAUDE.md SSR-fetch convention) and hands them to the
 * client component. Browser-side filter changes refetch via relative /api/...
 * URLs which traverse the /api/[...path] route-handler proxy.
 */

import { Suspense } from "react";
import { _apiFetch, type ActorListResponse } from "@/app/api-client";
import ActorsClient from "./ActorsClient";

export default async function ActorsPage() {
  let initialData: ActorListResponse | null = null;
  try {
    const res = await _apiFetch("/api/actors?limit=50", { cache: "no-store" });
    if (res.ok) {
      initialData = (await res.json()) as ActorListResponse;
    }
  } catch {
    initialData = null;
  }
  return (
    <Suspense fallback={<div className="p-8 text-muted-foreground text-sm">Loading actors…</div>}>
      <ActorsClient initialData={initialData} />
    </Suspense>
  );
}
