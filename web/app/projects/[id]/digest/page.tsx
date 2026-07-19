/**
 * /projects/[id]/digest - Daily Digest viewer page.
 *
 * Server Component. Fetches latest digest + project AI settings from backend,
 * then hands result to DigestView (client component) which owns the
 * "Generate now" interaction and markdown-lite rendering.
 */

import { DigestView } from "./DigestView";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function DigestPage({ params }: Props) {
  const { id } = await params;
  return <DigestView projectId={id} />;
}
