/**
 * /projects/[id]/easm — EASM Dashboard page.
 *
 * Server component: minimal wrapper that hands project ID to the client shell.
 * Layout.tsx already fetches project detail and renders the
 * breadcrumb + ProjectTabs strip — no duplicate fetch needed here.
 *
 * EASMDashboardClient owns all state: filter state, findings list,
 * safelist data, 24h-banner gating, and scan controls.
 */

import { EASMDashboardClient } from "./EASMDashboardClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EASMDashboardPage({ params }: Props) {
  const { id: projectId } = await params;
  return <EASMDashboardClient projectId={projectId} />;
}
