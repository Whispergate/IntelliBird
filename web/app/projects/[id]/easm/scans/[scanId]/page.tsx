/**
 * Scan Detail page — (UI-SPEC §Surface 6).
 *
 * Server component rendering ScanDetailClient.
 */

import type { Metadata } from "next";
import { ScanDetailClient } from "./ScanDetailClient";

interface PageProps {
  params: Promise<{ id: string; scanId: string }>;
}

export const metadata: Metadata = {
  title: "Scan Detail — IntelliBird",
};

export default async function ScanDetailPage({ params }: PageProps) {
  const { id, scanId } = await params;
  return <ScanDetailClient projectId={id} scanId={scanId} />;
}
