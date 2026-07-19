/**
 * /projects/[id]/scoring - Admin Scoring Config page.
 *
 * Server Component wrapper. Mirrors /projects/[id]/brand/page.tsx pattern exactly.
 * Hands the project id down to ScoringTabContent (client component) which owns
 * all form state, data fetching, and interactive behaviour.
 */

import { ScoringTabContent } from "./ScoringTabContent";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ScoringPage({ params }: Props) {
  const { id } = await params;
  return <ScoringTabContent projectId={id} />;
}
