/**
 * /projects/[id]/tiber - TIBER Reports list page.
 * UI-SPEC §Surface 1.
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
