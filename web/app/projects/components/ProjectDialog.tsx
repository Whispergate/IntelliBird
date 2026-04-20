"use client";

/**
 * ProjectDialog — create/edit modal for a project.
 *
 * Pattern mirrors web/app/sources/components/SourceDialog.tsx (shadcn Dialog
 * + react-hook-form + zod resolver). Submit CTA uses signal amber (reserved
 * for primary CTAs per UI-SPEC §Color).
 *
 * Fields (UI-SPEC §Component Inventory ProjectDialog):
 *   - name            (1..200 chars, required)
 *   - engagement_type (one of 5 enum literals, required)
 *   - description     (<=2000 chars, optional)
 *
 * Engagement type literals match backend/app/schemas/projects.py exactly.
 */

import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type {
  EngagementType,
  ProjectCreateBody,
  ProjectResponse,
} from "../lib/api";

const ENGAGEMENT_OPTIONS: ReadonlyArray<{ value: EngagementType; label: string }> = [
  { value: "red_team", label: "Red Team" },
  { value: "tiber", label: "TIBER" },
  { value: "bbest", label: "BBEST" },
  { value: "internal", label: "Internal" },
  { value: "intel_only", label: "Intel-only" },
] as const;

const schema = z.object({
  name: z.string().min(1, "Name is required.").max(200, "Name must be 200 characters or fewer."),
  engagement_type: z.enum([
    "red_team",
    "tiber",
    "bbest",
    "internal",
    "intel_only",
  ]),
  description: z.string().max(2000, "Description must be 2000 characters or fewer.").optional(),
});

type FormValues = z.infer<typeof schema>;

type Props = {
  open: boolean;
  mode: "add" | "edit";
  initial?: ProjectResponse;
  onSubmit: (body: ProjectCreateBody) => void | Promise<void>;
  onClose: () => void;
};

const DEFAULTS: FormValues = {
  name: "",
  engagement_type: "internal",
  description: "",
};

export function ProjectDialog({
  open,
  mode,
  initial,
  onSubmit,
  onClose,
}: Props) {
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULTS,
  });

  // Sync form state when (mode, initial) change — ProjectDialog is always
  // mounted so useForm only inits once at mount time (same pattern as
  // SourceDialog).
  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && initial) {
      form.reset({
        name: initial.name,
        engagement_type: initial.engagement_type,
        description: initial.description ?? "",
      });
    } else {
      form.reset(DEFAULTS);
    }
  }, [open, mode, initial, form]);

  async function handleSubmit(values: FormValues) {
    await onSubmit({
      name: values.name,
      engagement_type: values.engagement_type,
      description: values.description?.trim() ? values.description : null,
    });
  }

  const title = mode === "edit" ? "Edit Project" : "New Project";
  const submitLabel = mode === "edit" ? "Save changes" : "Save";

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(handleSubmit)}
            className="space-y-4"
          >
            <DialogHeader>
              <DialogTitle>{title}</DialogTitle>
            </DialogHeader>

            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input {...field} maxLength={200} autoFocus />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="engagement_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Engagement type</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select engagement type…" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {ENGAGEMENT_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    {/* Native textarea — shadcn Textarea primitive not installed
                        (per package.json). Matches SourceDialog precedent. */}
                    <textarea
                      {...field}
                      rows={4}
                      maxLength={2000}
                      className="w-full rounded-md border border-input bg-transparent p-2 text-sm"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter className="flex gap-2">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                type="submit"
                style={{
                  backgroundColor: "var(--brand-signal)",
                  color: "var(--brand-ink)",
                }}
                className="font-medium hover:opacity-90"
              >
                {submitLabel}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
