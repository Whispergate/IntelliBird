"use client";

import { useState, useRef } from "react";
import { toast } from "sonner";

import type { Webhook } from "@/app/api-client";
import {
  createWebhook,
  updateWebhook,
  deleteWebhook,
  listWebhooks,
} from "@/app/api-client";
import { Button } from "@/components/ui/button";

import { WebhookTable } from "./components/WebhookTable";
import { WebhookDialog } from "./components/WebhookDialog";
import { showDeleteConfirm } from "./components/WebhookDeleteConfirm";

type DialogState =
  | { open: false }
  | { open: true; mode: "add"; initialWebhook?: undefined }
  | { open: true; mode: "edit"; initialWebhook: Webhook };

export function WebhooksClient({ initialWebhooks }: { initialWebhooks: Webhook[] }) {
  const [webhooks, setWebhooks] = useState<Webhook[]>(initialWebhooks);
  const [dialog, setDialog] = useState<DialogState>({ open: false });
  // tableKey forces WebhookTable to remount when we mutate webhooks externally
  // (e.g. after optimistic delete) so WebhookTable re-initializes from initialWebhooks.
  const tableKeyRef = useRef(0);
  const [tableKey, setTableKey] = useState(0);

  async function refresh() {
    try {
      const fresh = await listWebhooks();
      setWebhooks(fresh);
      // Bump tableKey so WebhookTable remounts with fresh data
      tableKeyRef.current += 1;
      setTableKey(tableKeyRef.current);
    } catch {
      // swallow - table still shows stale rows
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function handleAdd(payload: any) {
    try {
      await createWebhook(payload);
      toast.success("Webhook added.");
      setDialog({ open: false });
      await refresh();
    } catch {
      toast.error("Failed to save webhook. Please try again.");
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function handleEdit(payload: any) {
    if (dialog.open && dialog.mode === "edit") {
      const id = dialog.initialWebhook.id;
      try {
        await updateWebhook(id, payload);
        toast.success("Webhook updated.");
        setDialog({ open: false });
        await refresh();
      } catch {
        toast.error("Failed to save webhook. Please try again.");
      }
    }
  }

  async function handleDelete(wh: Webhook) {
    const ok = await showDeleteConfirm(wh);
    if (!ok) return;
    try {
      await deleteWebhook(wh.id);
      setWebhooks((prev) => prev.filter((w) => w.id !== wh.id));
      // Bump tableKey so WebhookTable remounts with the filtered webhooks
      tableKeyRef.current += 1;
      setTableKey(tableKeyRef.current);
      toast.success("Webhook deleted.");
    } catch {
      toast.error("Failed to delete webhook.");
    }
  }

  return (
    <div>
      <div style={{ marginBottom: "2rem" }} className="flex items-center justify-between">
        <div>
          <h1 className="brand-display text-foreground">Webhooks</h1>
          <p className="text-[16px] leading-[1.7] text-muted-foreground mt-1">
            Register outbound alert destinations.
          </p>
        </div>
        <Button
          onClick={() => setDialog({ open: true, mode: "add" })}
          style={{ backgroundColor: "var(--brand-signal)", color: "var(--brand-ink)" }}
          className="font-medium hover:opacity-90"
        >
          Add Webhook
        </Button>
      </div>

      <WebhookTable
        key={tableKey}
        initialWebhooks={webhooks}
        onAdd={() => setDialog({ open: true, mode: "add" })}
        onEdit={(wh) => setDialog({ open: true, mode: "edit", initialWebhook: wh })}
        onDelete={handleDelete}
      />

      <WebhookDialog
        open={dialog.open}
        mode={dialog.open ? dialog.mode : "add"}
        initialWebhook={dialog.open && dialog.mode === "edit" ? dialog.initialWebhook : undefined}
        onSubmit={dialog.open && dialog.mode === "edit" ? handleEdit : handleAdd}
        onClose={() => setDialog({ open: false })}
      />
    </div>
  );
}
