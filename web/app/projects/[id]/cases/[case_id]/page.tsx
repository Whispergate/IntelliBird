import { _apiFetch } from "@/app/api-client";
import { CaseDetailClient } from "./CaseDetailClient";
import { notFound } from "next/navigation";

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ id: string; case_id: string }>;
}) {
  const { id, case_id } = await params;
  let caseData;
  try {
    const res = await _apiFetch(`/api/projects/${id}/cases/${case_id}`, { method: "GET" });
    if (!res.ok) notFound();
    caseData = await res.json();
  } catch {
    notFound();
  }
  return <CaseDetailClient projectId={id} initialCase={caseData} />;
}
