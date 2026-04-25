"use client";

/**
 * MonitoringConfigDrawer — per-source monitoring config slide-out panel.
 * Phase 16 plan 16-07. MON-04 dashboard requirement.
 *
 * Fields: last_event_sla_seconds, drift_z_high, drift_z_medium
 * Save → PATCH /api/admin/monitoring/sources/{id}
 * Reset → clears all three to null (backend defaults apply)
 * Toast on save success/failure via sonner.
 *
 * Uses shadcn Sheet (slide-out drawer pattern) mirroring EventDetailDrawer.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export type MonitoringSourceRow = {
  id: string;
  name: string;
  feed_type: string;
  last_event_at: string | null;
  silence_sla_seconds: number;
  sla_breached: boolean;
  silent_failure_count: number;
  parse_error_rate_1h: number;
  drift_z_score: number | null;
  drift_severity: string | null;
  sparkline: number[];
};

type MonitoringConfigDrawerProps = {
  source: MonitoringSourceRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
};

type ConfigFields = {
  last_event_sla_seconds: string;
  drift_z_high: string;
  drift_z_medium: string;
};

function emptyFields(source: MonitoringSourceRow | null): ConfigFields {
  return {
    last_event_sla_seconds: source ? String(source.silence_sla_seconds) : "",
    drift_z_high: "",
    drift_z_medium: "",
  };
}

export function MonitoringConfigDrawer({
  source,
  open,
  onOpenChange,
  onSaved,
}: MonitoringConfigDrawerProps) {
  const [fields, setFields] = useState<ConfigFields>(emptyFields(source));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (source) {
      setFields(emptyFields(source));
    }
  }, [source?.id]);

  function updateField(key: keyof ConfigFields, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  function handleReset() {
    setFields({
      last_event_sla_seconds: "",
      drift_z_high: "",
      drift_z_medium: "",
    });
  }

  async function handleSave() {
    if (!source) return;
    setSaving(true);
    try {
      const payload: Record<string, number | null> = {
        last_event_sla_seconds:
          fields.last_event_sla_seconds.trim() !== ""
            ? Number(fields.last_event_sla_seconds)
            : null,
        drift_z_high:
          fields.drift_z_high.trim() !== ""
            ? Number(fields.drift_z_high)
            : null,
        drift_z_medium:
          fields.drift_z_medium.trim() !== ""
            ? Number(fields.drift_z_medium)
            : null,
      };
      const res = await fetch(`/api/admin/monitoring/sources/${source.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail =
          typeof body?.detail === "string" ? body.detail : res.statusText;
        toast.error(`Save failed: ${detail}`);
        return;
      }
      toast.success("Monitoring config saved.");
      onSaved();
      onOpenChange(false);
    } catch (err) {
      toast.error(
        `Save failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[400px] sm:max-w-[400px] overflow-y-auto p-0"
      >
        <SheetHeader
          className="p-4 border-b sticky top-0 z-10"
          style={{ background: "hsl(var(--card))" }}
        >
          <div className="flex items-start justify-between gap-2">
            <SheetTitle className="brand-heading text-foreground leading-snug">
              {source?.name ?? "Monitoring Config"}
            </SheetTitle>
            <SheetClose />
          </div>
          {source && (
            <p className="text-xs text-muted-foreground mt-1">
              {source.feed_type.toUpperCase()} source — edit per-source monitoring overrides
            </p>
          )}
        </SheetHeader>

        <div className="p-4 flex flex-col gap-5">
          {/* SLA field */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="mc-sla" className="brand-caption text-muted-foreground">
              SILENCE SLA (seconds)
            </Label>
            <Input
              id="mc-sla"
              type="number"
              min={0}
              placeholder="Default per feed type"
              value={fields.last_event_sla_seconds}
              onChange={(e) =>
                updateField("last_event_sla_seconds", e.target.value)
              }
            />
            <p className="text-xs text-muted-foreground">
              Alert if no events arrive within this window. Leave empty to use feed-type default.
            </p>
          </div>

          {/* Drift z high */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="mc-z-high" className="brand-caption text-muted-foreground">
              DRIFT Z-SCORE HIGH THRESHOLD
            </Label>
            <Input
              id="mc-z-high"
              type="number"
              min={0}
              max={10}
              step={0.1}
              placeholder="Default: 3.0"
              value={fields.drift_z_high}
              onChange={(e) => updateField("drift_z_high", e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              z-score above this → HIGH severity drift alert.
            </p>
          </div>

          {/* Drift z medium */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="mc-z-medium" className="brand-caption text-muted-foreground">
              DRIFT Z-SCORE MEDIUM THRESHOLD
            </Label>
            <Input
              id="mc-z-medium"
              type="number"
              min={0}
              max={10}
              step={0.1}
              placeholder="Default: 2.0"
              value={fields.drift_z_medium}
              onChange={(e) => updateField("drift_z_medium", e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              z-score above this (but below high threshold) → MEDIUM severity drift alert.
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleReset}
              disabled={saving}
            >
              Reset to defaults
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving || !source}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
