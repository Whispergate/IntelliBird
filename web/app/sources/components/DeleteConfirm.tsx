"use client";

import type { Source } from "@/app/api-client";
import { getSourceEventCount } from "@/app/api-client";

/**
 * Fetch the event count for a source, then open the native browser confirm
 * dialog with the verbatim message. Native `confirm` is intentional
 * per 03-CONTEXT - do NOT replace with shadcn AlertDialog.
 *
 * On `getSourceEventCount` error, falls back to "?" as the count so the
 * operator can still see the confirm and decide.
*/
export async function showDeleteConfirm(source: Source): Promise<boolean> {
  let count: number | "?";
  try {
    const res = await getSourceEventCount(source.id);
    count = res.count;
  } catch {
    count = "?";
  }
  const message =
    `Delete source "${source.name}"? ${count} existing events will keep ` +
    `source_id=NULL (provenance lost but events retained).`;
  return window.confirm(message);
}
