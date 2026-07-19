"use client";

/**
 * ScopeRowDialog
 *
 * Add a scope row for one scope_type. Fields:
 *   - value   (required; dispatched to per-type validator on submit)
 *   - contact (optional; <=400 chars)
 *   - exclude (default false)
 *   - active_test_scope (default false)
 *   - intel_scope (default true)
 *
 * Validation (UI-SPEC §Error states - byte-exact copy):
 *   - CIDR:  "Enter a valid CIDR block, e.g. 10.0.0.0/24."
 *   - FQDN:  "Enter a valid domain, e.g. example.com."
 *   - AS int: "AS number must be a positive integer."
 *   - Cert: "Enter a SHA-1 (40 hex) or SHA-256 (64 hex) certificate fingerprint."
 *   - Both flags off: "Row must target at least intel or active test."
 *
 * Per-type validation runs client-side (lib/scope-validators.ts) pre-submit -
 * identical error copy to the backend, so a rejected input looks the same
 * whether the network round-trip happened or not.
 *
 * Plan 10-10 specifies this as the primary editable path; toggles on existing
 * rows are read-only (see ScopeRowTable doc header).
 */

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import type { ScopeRowCreateBody, ScopeType } from "../../lib/api";
import { validateScopeValue } from "../../lib/scope-validators";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

// Zod schema enforces the "at least one of intel/active_test" invariant with
// the exact UI-SPEC error string. Per-value validation (CIDR/FQDN/AS/cert) is
// NOT embedded here because the copy is type-dependent - we run it manually
// in submit() and push the result into `valueError` state for inline display.
const schema = z
  .object({
    value: z.string().min(1, "Value is required."),
    contact: z.string().max(400).optional(),
    exclude: z.boolean(),
    active_test_scope: z.boolean(),
    intel_scope: z.boolean(),
  })
  .refine((v) => v.active_test_scope || v.intel_scope, {
    message: "Row must target at least intel or active test.",
    // Attach the both-off error to `intel_scope` so FormState sees it - the
    // component reads from form.formState.errors.intel_scope for display.
    path: ["intel_scope"],
  });

type FormValues = z.infer<typeof schema>;

const DEFAULTS: FormValues = {
  value: "",
  contact: "",
  exclude: false,
  active_test_scope: false,
  intel_scope: true,
};

export function ScopeRowDialog({
  open,
  scopeType,
  addLabel,
  onSubmit,
  onClose,
}: {
  open: boolean;
  /** One of the 7 ScopeType literals - dispatches the per-type validator. */
  scopeType: ScopeType;
  /** Dialog header + primary CTA hint (e.g. "Add IP range"). */
  addLabel: string;
  /** Parent posts the validated body. */
  onSubmit: (body: ScopeRowCreateBody) => Promise<void> | void;
  onClose: () => void;
}) {
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULTS,
  });
  // Per-type validation error (CIDR/FQDN/AS/cert) - distinct from zod errors.
  const [valueError, setValueError] = useState<string | null>(null);

  // Reset the form whenever the dialog re-opens or the scope type switches;
  // pattern mirrors ProjectDialog.
  useEffect(() => {
    if (open) {
      form.reset(DEFAULTS);
      setValueError(null);
    }
  }, [open, scopeType, form]);

  async function submit(v: FormValues) {
    setValueError(null);
    let canonical: string;
    try {
      canonical = validateScopeValue(scopeType, v.value);
    } catch (err) {
      setValueError(err instanceof Error ? err.message : "Invalid value.");
      return;
    }
    await onSubmit({
      scope_type: scopeType,
      value: canonical,
      contact: v.contact?.trim() ? v.contact.trim() : null,
      exclude: v.exclude,
      active_test_scope: v.active_test_scope,
      intel_scope: v.intel_scope,
    });
  }

  // Pull the both-flags-off error from react-hook-form's formState.
  const bothFlagsError = form.formState.errors.intel_scope?.message;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{addLabel}</DialogTitle>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(submit)} className="space-y-4">
          <div>
            <Label htmlFor="scope-value">Value</Label>
            <Input
              id="scope-value"
              {...form.register("value")}
              maxLength={1024}
              autoFocus
              autoComplete="off"
            />
            {valueError && (
              <p className="text-destructive text-sm mt-1">{valueError}</p>
            )}
            {!valueError && form.formState.errors.value?.message && (
              <p className="text-destructive text-sm mt-1">
                {form.formState.errors.value.message}
              </p>
            )}
          </div>

          <div>
            <Label htmlFor="scope-contact">Contact (optional)</Label>
            <Input
              id="scope-contact"
              {...form.register("contact")}
              maxLength={400}
              autoComplete="off"
            />
          </div>

          <div className="flex items-center gap-2">
            <Switch
              checked={form.watch("exclude")}
              onCheckedChange={(v) => form.setValue("exclude", v)}
              aria-label="Exclude"
            />
            <Label className="cursor-pointer">
              Exclude (subtract from include matches)
            </Label>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              checked={form.watch("active_test_scope")}
              onCheckedChange={(v) => form.setValue("active_test_scope", v)}
              aria-label="Active test scope"
            />
            <Label className="cursor-pointer">Active test scope</Label>
          </div>

          <div className="flex items-center gap-2">
            <Switch
              checked={form.watch("intel_scope")}
              onCheckedChange={(v) => form.setValue("intel_scope", v)}
              aria-label="Intel scope"
            />
            <Label className="cursor-pointer">Intel scope (default)</Label>
          </div>

          {bothFlagsError && (
            <p className="text-destructive text-sm">{bothFlagsError}</p>
          )}

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
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
