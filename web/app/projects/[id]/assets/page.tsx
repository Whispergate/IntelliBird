/**
 * /projects/[id]/assets - Assets Dashboard page.
 *
 * Server component shell: hands project ID to the client component.
 * Layout.tsx already renders the breadcrumb + ProjectTabs strip.
 *
 * AssetsClient owns all state: filter state, URL sync, summary fetch,
 * and placeholders for the table/drawer which land in 12.1-05b.
 */

import AssetsClient from "./AssetsClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AssetsPage({ params }: Props) {
  const { id: projectId } = await params;
  return <AssetsClient projectId={projectId} />;
}
