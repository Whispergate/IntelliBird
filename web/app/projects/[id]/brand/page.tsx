/**
 * /projects/[id]/brand — Brand Protection Dashboard page (Phase 12 plan 12-08).
 *
 * Server component wrapper — hands project id to BrandDashboardClient which
 * owns filter state, data fetching, banner gating, and table rendering.
 * Mirrors Phase 11 EASM page.tsx shape exactly.
 *
 * Phase 32 / CERT-03: also fetches project certstream_enabled flag and renders
 * CTLogModeSection (Lead+ gated) below the dashboard.
 */

import { fetchProjectDetail } from "@/app/projects/lib/api";
import { BrandDashboardClient } from "./BrandDashboardClient";
import { CTLogModeSection } from "./CTLogModeSection";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function BrandDashboardPage({ params }: Props) {
  const { id } = await params;
  const project = await fetchProjectDetail(id);
  return (
    <>
      <BrandDashboardClient projectId={id} />
      <CTLogModeSection
        projectId={id}
        certstreamEnabled={project.certstream_enabled}
      />
    </>
  );
}
