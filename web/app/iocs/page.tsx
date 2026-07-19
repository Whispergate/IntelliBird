/**
 * /iocs - Global IOC search page.
 *
 * RSC wrapper: reads ?q from searchParams, fetches initial results server-side
 * via _apiFetch (per CLAUDE.md SSR convention), hands them to IOCsGlobalClient.
 * No projectId - cross-project scope; ACL handled by build_ioc_scope_predicate
 * on the backend (Admin sees all projects, other roles see their own projects).
 */
import { _apiFetch, type IOCRead } from "@/app/api-client";
import { IOCsGlobalClient } from "./IOCsGlobalClient";

interface Props {
  searchParams: Promise<{ q?: string }>;
}

export default async function GlobalIOCsPage({ searchParams }: Props) {
  const { q } = await searchParams;
  let initialRows: IOCRead[] = [];
  try {
    const qs = new URLSearchParams({ status: "active", limit: "50" });
    if (q) qs.set("q", q);
    const res = await _apiFetch(`/api/iocs?${qs.toString()}`, {
      cache: "no-store",
    });
    if (res.ok) {
      initialRows = (await res.json()) as IOCRead[];
    }
  } catch {
    initialRows = [];
  }
  return <IOCsGlobalClient initialRows={initialRows} initialQ={q ?? ""} />;
}
