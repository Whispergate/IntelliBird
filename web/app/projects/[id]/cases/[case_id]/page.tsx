import { _apiFetch } from "@/app/api-client";
import { CaseDetailClient } from "./CaseDetailClient";
import { notFound } from "next/navigation";

export default async function CaseDetailPage({
  params,
}: {
  params: { id: string; case_id: string };
}) {
  let caseData;
  try {
    const res = await _apiFetch(`/api/projects/${params.id}/cases/${params.case_id}`, { method: "GET" });
    if (!res.ok) notFound();
    caseData = await res.json();
  } catch {
    notFound();
  }
  return <CaseDetailClient projectId={params.id} initialCase={caseData} />;
}
