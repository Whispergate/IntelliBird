"use client";

import { useState, useRef } from "react";
import { toast } from "sonner";

import type { Source } from "@/app/api-client";
import {
  createSource,
  updateSource,
  deleteSource,
  fetchSources,
} from "@/app/api-client";
import { Button } from "@/components/ui/button";

import { SourceTable } from "./components/SourceTable";
import { SourceDialog } from "./components/SourceDialog";
import { showDeleteConfirm } from "./components/DeleteConfirm";

type DialogState =
  | { open: false }
  | { open: true; mode: "add"; initialSource?: undefined }
  | { open: true; mode: "edit"; initialSource: Source };

export function SourcesClient({ initialSources }: { initialSources: Source[] }) {
  const [sources, setSources] = useState<Source[]>(initialSources);
  const [dialog, setDialog] = useState<DialogState>({ open: false });
  // tableKey forces SourceTable to remount when we mutate sources externally
  // (e.g. after optimistic delete) so SourceTable re-initializes from initialSources.
  const tableKeyRef = useRef(0);
  const [tableKey, setTableKey] = useState(0);

  async function refresh() {
    try {
      const fresh = await fetchSources();
      setSources(fresh);
      // Bump tableKey so SourceTable remounts with fresh data
      tableKeyRef.current += 1;
      setTableKey(tableKeyRef.current);
    } catch {
      // swallow — table still shows stale rows
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function handleAdd(payload: any) {
    try {
      await createSource(payload);
      toast.success("Source added.");
      setDialog({ open: false });
      await refresh();
    } catch {
      toast.error("Failed to save source. Please try again.");
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function handleEdit(payload: any) {
    if (dialog.open && dialog.mode === "edit") {
      const id = dialog.initialSource.id;
      try {
        await updateSource(id, payload);
        toast.success("Source updated.");
        setDialog({ open: false });
        await refresh();
      } catch {
        toast.error("Failed to save source. Please try again.");
      }
    }
  }

  async function handleDelete(src: Source) {
    const ok = await showDeleteConfirm(src);
    if (!ok) return;
    try {
      await deleteSource(src.id);
      setSources((prev) => prev.filter((s) => s.id !== src.id));
      // Bump tableKey so SourceTable remounts with the filtered sources
      tableKeyRef.current += 1;
      setTableKey(tableKeyRef.current);
      toast.success("Source deleted.");
    } catch {
      toast.error("Failed to delete source.");
    }
  }

  return (
    <div>
      <div style={{ marginBottom: "2rem" }} className="flex items-center justify-between">
        <div>
          <h1 className="brand-display text-foreground">Sources</h1>
          <p className="text-[16px] leading-[1.7] text-muted-foreground mt-1">
            Add and manage threat-intel feeds.
          </p>
        </div>
        <Button
          onClick={() => setDialog({ open: true, mode: "add" })}
          style={{ backgroundColor: "var(--brand-signal)", color: "var(--brand-ink)" }}
          className="font-medium hover:opacity-90"
        >
          Add Source
        </Button>
      </div>

      <SourceTable
        key={tableKey}
        initialSources={sources}
        onAdd={() => setDialog({ open: true, mode: "add" })}
        onEdit={(src) => setDialog({ open: true, mode: "edit", initialSource: src })}
        onDelete={handleDelete}
      />

      <SourceDialog
        open={dialog.open}
        mode={dialog.open ? dialog.mode : "add"}
        initialSource={dialog.open && dialog.mode === "edit" ? dialog.initialSource : undefined}
        onSubmit={dialog.open && dialog.mode === "edit" ? handleEdit : handleAdd}
        onClose={() => setDialog({ open: false })}
      />
    </div>
  );
}
