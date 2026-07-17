/**
 * /projects/[id]/tiber/[report_id] — TIBER Report Editor page.
 * UI-SPEC §Surface 2.
 *
 * Server component: fetches report + actors + scenarios, passes to TIBERReportEditor.
 */

import { TIBERReportEditor } from "./TIBERReportEditor";
import { getReport, listActors, listScenarios } from "../lib/api";

interface Props {
  params: Promise<{ id: string; report_id: string }>;
}

export default async function TIBERReportEditorPage({ params }: Props) {
  const { id, report_id } = await params;

  // Fetch report data server-side via _apiFetch (bearer injected automatically)
  const [report, actors, scenarios] = await Promise.all([
    getReport({ projectId: id, reportId: report_id }),
    listActors({ projectId: id, reportId: report_id }),
    listScenarios({ projectId: id, reportId: report_id }),
  ]);

  return (
    <TIBERReportEditor
      projectId={id}
      report={report}
      initialActors={actors}
      initialScenarios={scenarios}
    />
  );
}
