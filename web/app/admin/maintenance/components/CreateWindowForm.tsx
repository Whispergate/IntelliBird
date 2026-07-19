"use client";

/**
 * CreateWindowForm - react-hook-form + zod form to POST /api/admin/maintenance-window.
 * H-7 maintenance window management.
 *
 * Fields:
 *   start_at  - datetime-local (required)
 *   end_at    - datetime-local (required, must be after start_at)
 *   reason    - textarea (optional, max 1000 chars)
 *
 * Client-side validation via zod. Toast on success/failure.
 * Calls onSuccess() after successful POST so parent can refresh the list.
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";

const windowSchema = z
  .object({
    start_at: z.string().min(1, "Start time is required"),
    end_at: z.string().min(1, "End time is required"),
    reason: z.string().max(1000, "Reason must be 1000 characters or fewer").optional(),
  })
  .refine(
    (data) => {
      if (!data.start_at || !data.end_at) return true;
      return new Date(data.end_at) > new Date(data.start_at);
    },
    {
      message: "End time must be after start time",
      path: ["end_at"],
    },
  );

type WindowFormValues = z.infer<typeof windowSchema>;

type CreateWindowFormProps = {
  onSuccess: () => void;
};

function toLocalDatetimeString(d: Date): string {
  // Format as "YYYY-MM-DDTHH:mm" for datetime-local input default
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    d.getFullYear() +
    "-" +
    pad(d.getMonth() + 1) +
    "-" +
    pad(d.getDate()) +
    "T" +
    pad(d.getHours()) +
    ":" +
    pad(d.getMinutes())
  );
}

export function CreateWindowForm({ onSuccess }: CreateWindowFormProps) {
  const [submitting, setSubmitting] = useState(false);

  const now = new Date();
  const thirtyMinLater = new Date(now.getTime() + 30 * 60 * 1000);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<WindowFormValues>({
    resolver: zodResolver(windowSchema),
    defaultValues: {
      start_at: toLocalDatetimeString(now),
      end_at: toLocalDatetimeString(thirtyMinLater),
      reason: "",
    },
  });

  async function onSubmit(values: WindowFormValues) {
    setSubmitting(true);
    try {
      const payload = {
        start_at: new Date(values.start_at).toISOString(),
        end_at: new Date(values.end_at).toISOString(),
        reason: values.reason?.trim() || null,
      };
      const res = await fetch("/api/admin/maintenance-window", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail =
          typeof body?.detail === "string" ? body.detail : res.statusText;
        toast.error(`Failed to create window: ${detail}`);
        return;
      }
      toast.success("Maintenance window created.");
      reset({
        start_at: toLocalDatetimeString(new Date()),
        end_at: toLocalDatetimeString(
          new Date(Date.now() + 30 * 60 * 1000),
        ),
        reason: "",
      });
      onSuccess();
    } catch (err) {
      toast.error(
        `Error: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <form
        onSubmit={handleSubmit(onSubmit)}
        className="p-4 flex flex-col gap-4"
      >
        <h2 className="brand-caption text-muted-foreground text-xs uppercase tracking-wide">
          Create maintenance window
        </h2>

        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="mw-start" className="brand-caption text-xs text-muted-foreground uppercase">
              Start time
            </Label>
            <Input
              id="mw-start"
              type="datetime-local"
              {...register("start_at")}
              className={errors.start_at ? "border-destructive" : ""}
            />
            {errors.start_at && (
              <p className="text-xs" style={{ color: "hsl(var(--destructive))" }}>
                {errors.start_at.message}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="mw-end" className="brand-caption text-xs text-muted-foreground uppercase">
              End time
            </Label>
            <Input
              id="mw-end"
              type="datetime-local"
              {...register("end_at")}
              className={errors.end_at ? "border-destructive" : ""}
            />
            {errors.end_at && (
              <p className="text-xs" style={{ color: "hsl(var(--destructive))" }}>
                {errors.end_at.message}
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="mw-reason" className="brand-caption text-xs text-muted-foreground uppercase">
            Reason (optional)
          </Label>
          <textarea
            id="mw-reason"
            rows={2}
            placeholder="e.g. Planned stack restart for 016 migration"
            className="flex min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            {...register("reason")}
          />
          {errors.reason && (
            <p className="text-xs" style={{ color: "hsl(var(--destructive))" }}>
              {errors.reason.message}
            </p>
          )}
        </div>

        <div className="flex justify-end">
          <Button type="submit" disabled={submitting}>
            {submitting ? "Creating…" : "Create window"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
