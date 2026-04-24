/**
 * /projects/[id]/brand — Brand Protection Dashboard page (Phase 12 plan 12-08).
 *
 * Server component wrapper — hands project id to BrandDashboardClient which
 * owns filter state, data fetching, banner gating, and table rendering.
 * Mirrors Phase 11 EASM page.tsx shape exactly.
 */

import { BrandDashboardClient } from "./BrandDashboardClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function BrandDashboardPage({ params }: Props) {
  const { id } = await params;
  return <BrandDashboardClient projectId={id} />;
}
