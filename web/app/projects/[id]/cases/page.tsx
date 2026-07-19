import { _apiFetch } from "@/app/api-client";
import CasesClient from "./CasesClient";
import type { CaseRow } from "@/app/api-client";

export default async function CasesPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ view?: string }>;
}) {
  const { id: projectId } = await params;
  const { view: viewParam } = await searchParams;
  const view = viewParam === "table" ? "table" : "kanban";

  let initialCases: CaseRow[] = [];
  try {
    const res = await _apiFetch(`/api/projects/${projectId}/cases?limit=200`);
    if (res.ok) {
      const data = await res.json();
      initialCases = (data.items ?? []) as CaseRow[];
    }
  } catch {
    // render empty state; CasesClient will handle error display
  }

  return (
    <CasesClient
      projectId={projectId}
      initialCases={initialCases}
      initialView={view}
    />
  );
}
