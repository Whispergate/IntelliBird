/**
 * Scan History page — Phase 11 plan 11-09 (UI-SPEC §Surface 5).
 *
 * Server component rendering ScanHistoryClient.
 */

import type { Metadata } from "next";
import { ScanHistoryClient } from "./ScanHistoryClient";

interface PageProps {
  params: Promise<{ id: string }>;
}

export const metadata: Metadata = {
  title: "Scan History — IntelliBird",
};

export default async function ScanHistoryPage({ params }: PageProps) {
  const { id } = await params;
  return <ScanHistoryClient projectId={id} />;
}
