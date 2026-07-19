"use client";

/**
 * useNoteAutosave - (UI-SPEC §Surface 6, Note section).
 *
 * Debounced client-side autosave for the asset-detail note editor.
 *
 * Lifecycle state machine:
 *   idle → (user types, draft !== initialNote) → typing
 *   typing → (1500ms quiet) → saving
 *   saving → (fetch ok) → saved
 *   saving → (fetch fail) → error
 *   any → (user types again) → typing (cancels pending timer)
 *
 * Disabled for Viewer/Observer roles (per UI-SPEC Authority Matrix) - when
 * `disabled` is true the effect is a no-op; the textarea is expected to
 * render disabled at the call site.
 */

import { useEffect, useState } from "react";

export type AutosaveStatus = "idle" | "typing" | "saving" | "saved" | "error";

export interface UseNoteAutosaveParams {
  projectId: string;
  assetId: string | null;
  initialNote: string;
  disabled: boolean;
  /** Debounce window in ms. Default: 1500 per UI-SPEC §Surface 6. */
  debounceMs?: number;
}

export interface UseNoteAutosaveReturn {
  draft: string;
  setDraft: (next: string) => void;
  status: AutosaveStatus;
  savedAt: Date | null;
  retry: () => void;
}

export function useNoteAutosave(
  params: UseNoteAutosaveParams,
): UseNoteAutosaveReturn {
  const { projectId, assetId, initialNote, disabled } = params;
  const debounceMs = params.debounceMs ?? 1500;

  const [draft, setDraft] = useState<string>(initialNote);
  const [status, setStatus] = useState<AutosaveStatus>("idle");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  // When the backing asset changes, reset draft/status to track the new note.
  useEffect(() => {
    setDraft(initialNote);
    setStatus("idle");
    setSavedAt(null);
  }, [assetId, initialNote]);

  useEffect(() => {
    if (disabled) return;
    if (!assetId) return;
    // Nothing to save until the user actually changes the text.
    if (draft === initialNote) return;

    setStatus("typing");
    const timer = setTimeout(async () => {
      setStatus("saving");
      try {
        const res = await fetch(
          `/api/projects/${projectId}/assets/${assetId}/note`,
          {
            method: "PATCH",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ note: draft }),
          },
        );
        if (!res.ok) throw new Error(`save_failed ${res.status}`);
        setStatus("saved");
        setSavedAt(new Date());
      } catch {
        setStatus("error");
      }
    }, debounceMs);

    return () => clearTimeout(timer);
  }, [draft, disabled, assetId, projectId, initialNote, debounceMs, retryKey]);

  const retry = () => setRetryKey((k) => k + 1);

  return { draft, setDraft, status, savedAt, retry };
}
