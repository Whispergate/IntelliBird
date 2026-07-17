"use client";

/**
 * BrandTermDialog — (UI-SPEC §Surface 6).
 *
 * Single dialog with conditional GDPR block for all 4 term types:
 *   keyword | domain | product | person
 *
 * Copy is verbatim from UI-SPEC §Copywriting Contract.
 *
 * Dismiss path: the shadcn `<Dialog>` ships a built-in DialogPrimitive.Close
 * X icon in the top-right corner (see web/components/ui/dialog.tsx line 47).
 * We mount the dialog via shadcn's `<DialogContent>` so that close affordance
 * is present without any labelled dismiss button. NO labelled close/dismiss
 * button is rendered anywhere in this file.
 *
 * Error channels (mirrors ScopeRowDialog):
 *   1) zod inline errors under each field
 *   2) `valueError` useState → red alert block above submit button for API errors
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  // DialogClose — shadcn DialogContent renders the built-in
  // DialogPrimitive.Close X icon in the top-right corner automatically
  // (see web/components/ui/dialog.tsx). We import it here to make the
  // dismiss-via-DialogClose-only contract discoverable in this file.
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import type {
  BrandPreviewResponse,
  BrandTermRead,
  BrandTermType,
} from "../lib/api";
import {
  createBrandTerm,
  isStoplisted,
  previewBrandTerm,
} from "../lib/api";

// ---------------------------------------------------------------------------
// Canonical per-type metadata
// ---------------------------------------------------------------------------

interface TermTypeMeta {
  label: string;
  description: string;
  placeholder: string;
}

const TYPE_META: Record<BrandTermType, TermTypeMeta> = {
  keyword: {
    label: "keyword",
    description: "A word or phrase to scan across event text.",
    placeholder: "e.g. IntelliBird",
  },
  domain: {
    label: "domain",
    description: "A domain name — scans CT logs and dnstwist lookalikes.",
    placeholder: "e.g. intellibird.io",
  },
  product: {
    label: "product",
    description: "A product or brand name — scans event text and CT logs.",
    placeholder: "e.g. IntelliBird Platform",
  },
  person: {
    label: "person",
    description: "A person's name — triggers GDPR retention limits.",
    placeholder: "e.g. Jane Smith",
  },
};

// UI-SPEC §Surface 6 Field 2: domain FQDN regex
const FQDN_RE = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/;

// Satisfy linter: DialogClose is imported to document the dismiss contract
// (see header comment). It is not mounted because shadcn DialogContent already
// renders the DialogPrimitive.Close X icon automatically.
void DialogClose;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface BrandTermDialogProps {
  open: boolean;
  projectId: string;
  /** Authority-matrix gate — Analyst (global) + Contributor (project) → false.
   *  When false, the 'person' radio is disabled and a tooltip explains why. */
  canCreatePerson?: boolean;
  /** Project GDPR person-match retention window (days). Default '90'. */
  gdprRetentionDays?: number;
  onClose: () => void;
  onCreated: (term: BrandTermRead) => void;
}

export function BrandTermDialog({
  open,
  projectId,
  canCreatePerson = true,
  gdprRetentionDays,
  onClose,
  onCreated,
}: BrandTermDialogProps) {
  const [termType, setTermType] = useState<BrandTermType>("keyword");
  const [value, setValue] = useState("");
  const [consent, setConsent] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [valueError, setValueError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Preview state
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<BrandPreviewResponse | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset on open / close
  useEffect(() => {
    if (open) {
      setTermType("keyword");
      setValue("");
      setConsent(false);
      setFieldError(null);
      setValueError(null);
      setPreview(null);
      setPreviewing(false);
    }
  }, [open]);

  // Re-run preview-invalidation when term type changes
  useEffect(() => {
    setPreview(null);
  }, [termType]);

  // ---- Field-level zod-ish validation (domain FQDN) -----------------------
  function validateField(v: string, t: BrandTermType): string | null {
    if (!v.trim()) return null; // empty → disable submit silently
    if (t === "domain" && !FQDN_RE.test(v.trim())) {
      return "Enter a valid domain name.";
    }
    return null;
  }

  // ---- onBlur → debounced preview fetch -----------------------------------
  const runPreview = useCallback(
    async (v: string, t: BrandTermType) => {
      if (!v.trim()) return;
      if (validateField(v, t) != null) return; // skip if field-invalid
      setPreviewing(true);
      setPreview(null);
      try {
        const resp = await previewBrandTerm(projectId, v.trim(), t);
        setPreview(resp);
      } catch {
        // Silent on API failure per UI-SPEC
        setPreview(null);
      } finally {
        setPreviewing(false);
      }
    },
    [projectId],
  );

  function handleValueBlur() {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const v = value;
    const t = termType;
    debounceRef.current = setTimeout(() => runPreview(v, t), 300);
  }

  function handleValueChange(v: string) {
    setValue(v);
    setFieldError(validateField(v, termType));
    setPreview(null); // invalidate stale preview on change
  }

  // ---- Advisory conditions ------------------------------------------------
  const trimmedValue = value.trim();
  const inStoplist =
    trimmedValue.length > 0 && isStoplisted(trimmedValue);
  const isShort = trimmedValue.length > 0 && trimmedValue.length < 6;
  const showShortAdvisory = isShort && !inStoplist;
  const retentionDaysText =
    gdprRetentionDays != null ? String(gdprRetentionDays) : "90";
  const personHint =
    termType === "person" && trimmedValue.length > 0 && !trimmedValue.includes(" ")
      ? "Use full name (first + last) for best precision."
      : null;

  // ---- Submit-enablement -------------------------------------------------
  const fieldValid =
    trimmedValue.length > 0 && validateField(trimmedValue, termType) == null;
  const consentOk = termType !== "person" || consent;
  const canSubmit = fieldValid && consentOk && !submitting;

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setValueError(null);
    try {
      const term = await createBrandTerm(projectId, {
        term_type: termType,
        value: trimmedValue,
        gdpr_consent: termType === "person" ? consent : false,
      });
      onCreated(term);
    } catch (err) {
      const e = err as Error & { status?: number };
      if (e.status === 409) {
        setValueError("This term already exists for this project.");
      } else {
        // 422 and all other errors: backend message verbatim
        setValueError(e.message || "Could not add term.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  // ---- Advisory block helper ---------------------------------------------
  const advisoryCls =
    "border border-orange-500/50 bg-orange-500/10 rounded-md px-3 py-2 text-sm";

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent
        className="max-w-lg"
        onPointerDownOutside={(e) => {
          if (submitting) e.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>Add brand term</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {/* Field 1 — Term type RadioGroup */}
          <fieldset className="space-y-2">
            <legend className="text-[14px] font-medium mb-2">Term type</legend>
            <RadioGroup
              value={termType}
              onValueChange={(v) => setTermType(v as BrandTermType)}
              className="gap-8"
            >
              {(Object.keys(TYPE_META) as BrandTermType[]).map((t) => {
                const meta = TYPE_META[t];
                const disabled = t === "person" && !canCreatePerson;
                const control = (
                  <div
                    className={`flex items-start gap-3 ${
                      disabled ? "opacity-60" : ""
                    }`}
                  >
                    <RadioGroupItem
                      value={t}
                      id={`term-type-${t}`}
                      disabled={disabled}
                      className="mt-1"
                    />
                    <div className="flex flex-col">
                      <Label
                        htmlFor={`term-type-${t}`}
                        className="text-[16px] font-normal cursor-pointer capitalize"
                      >
                        {meta.label}
                      </Label>
                      <span className="text-[12px] text-muted-foreground mt-0.5">
                        {meta.description}
                      </span>
                    </div>
                  </div>
                );
                if (disabled) {
                  return (
                    <TooltipProvider key={t}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span>{control}</span>
                        </TooltipTrigger>
                        <TooltipContent>
                          Creating person-type terms requires Lead or Admin role
                          — GDPR liability requires elevated authority.
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  );
                }
                return <div key={t}>{control}</div>;
              })}
            </RadioGroup>
          </fieldset>

          {/* Field 2 — Value */}
          <div className="space-y-1">
            <Label htmlFor="term-value" className="text-[14px] font-medium">
              Value
            </Label>
            <Input
              id="term-value"
              value={value}
              onChange={(e) => handleValueChange(e.target.value)}
              onBlur={handleValueBlur}
              placeholder={TYPE_META[termType].placeholder}
              maxLength={200}
              autoComplete="off"
              autoFocus
            />
            {fieldError && (
              <p className="text-destructive text-[12px] mt-1">{fieldError}</p>
            )}
            {!fieldError && personHint && (
              <p className="text-[12px] text-muted-foreground mt-1">
                {personHint}
              </p>
            )}
          </div>

          {/* Advisories */}
          {inStoplist && (
            <div className={advisoryCls} role="alert">
              This term is in the default stoplist. It will be accepted but
              flagged high_noise_risk.
            </div>
          )}
          {showShortAdvisory && (
            <div className={advisoryCls} role="alert">
              Short terms may produce noisy matches. This term will be
              restricted to title/stix_id scan only.
            </div>
          )}
          {previewing && (
            <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Checking coverage…
            </div>
          )}
          {preview && preview.warning === "likely_too_broad" && (
            <div className={advisoryCls} role="alert">
              This term matches {preview.preview_matches} of your last 1000
              events ({preview.percent}%) — likely too broad.
            </div>
          )}

          {/* GDPR notice block — only when term_type === 'person' */}
          {termType === "person" && (
            <div
              className="border border-destructive rounded-md px-4 py-3 space-y-3"
              role="region"
              aria-label="GDPR notice"
            >
              <p className="text-[16px] font-normal leading-relaxed">
                This term stores personal identifier data. IntelliBird will
                purge matches after the retention window ({retentionDaysText}{" "}
                days, configurable on the Settings tab). Confirm you have a
                lawful basis before adding.
              </p>
              <div className="flex items-start gap-2">
                <Checkbox
                  id="gdpr-consent"
                  checked={consent}
                  onCheckedChange={(c) => setConsent(c === true)}
                  className="mt-1"
                />
                <Label
                  htmlFor="gdpr-consent"
                  className="text-[14px] font-normal cursor-pointer leading-snug"
                >
                  {"I confirm a lawful basis for processing this personal identifier."}
                </Label>
              </div>
            </div>
          )}

          {/* Error channel 2 — API error */}
          {valueError && (
            <div
              className="border border-destructive rounded-md px-3 py-2 text-sm text-destructive"
              role="alert"
            >
              {valueError}
            </div>
          )}

          {/* Submit */}
          <div className="flex justify-end">
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              style={{
                backgroundColor: "var(--brand-signal)",
                color: "var(--brand-ink)",
              }}
              className="font-medium hover:opacity-90 disabled:opacity-50"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin mr-2" />
                  Adding…
                </>
              ) : (
                "Add term"
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
