/**
 * /projects/[id]/tiber — TIBER Reports list page.
 * Phase 18 plan 18-06. UI-SPEC §Surface 1.
 *
 * Server component: passes projectId down to TIBERReportListClient which owns
 * all filter state and the "New report" dialog.
 */

import { TIBERReportListClient } from "./TIBERReportListClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function TIBERReportListPage({ params }: Props) {
  const { id } = await params;
  return <TIBERReportListClient projectId={id} />;
}
