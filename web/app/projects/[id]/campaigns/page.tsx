import { _apiFetch } from "@/app/api-client";
import type { CampaignListResponse } from "@/app/api-client";
import CampaignsClient from "./CampaignsClient";

export default async function CampaignsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: projectId } = await params;

  let initialData: CampaignListResponse = { items: [], next_cursor: null };
  try {
    const res = await _apiFetch(`/api/campaigns?project_id=${projectId}&limit=50`, {
      cache: "no-store",
    });
    if (res.ok) {
      initialData = (await res.json()) as CampaignListResponse;
    }
  } catch {
    // render empty state
  }

  return <CampaignsClient projectId={projectId} initialData={initialData} />;
}
