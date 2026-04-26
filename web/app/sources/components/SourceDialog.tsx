"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useRef, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";

import { Alert, AlertDescription } from "@/components/ui/alert";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { testConnection, fetchSourceTemplates } from "@/app/api-client";
import type { Source, SourceTemplate } from "@/app/api-client";

import { CredentialsField } from "./CredentialsField";
import { HtmlScrapeFields } from "./HtmlScrapeFields";
import { RetentionPresetPicker } from "./RetentionPresetPicker";
import {
  baseSourceFormSchema,
  buildCreatePayload,
  buildCredentialsDict,
  buildScrapeConfig,
  buildUpdatePayload,
  RETENTION_PRESETS,
  type SourceFormValues,
} from "../lib/sourceSchema";

type TestState =
  | { kind: "ok"; latency_ms: number; item_count_sampled: number }
  | { kind: "fail"; error_detail: string }
  | null;

type Props = {
  open: boolean;
  mode: "add" | "edit";
  initialSource?: Source;
  onSubmit: (
    payload:
      | ReturnType<typeof buildCreatePayload>
      | Record<string, unknown>,
  ) => void | Promise<void>;
  onClose: () => void;
};

function defaultValuesFor(
  mode: "add" | "edit",
  src?: Source,
): Partial<SourceFormValues> {
  if (mode === "add" || !src) {
    return {
      feed_type: "rss",
      poll_interval_number: 60,
      poll_interval_unit: "min",
      retention_preset: "standard",
      taxii_scheme: "none",
      enabled: true,
      // Quick task 260426-aas: new custom sources default to auto-discovery.
      scrape_mode: "auto",
    };
  }

  // Edit mode: derive poll interval unit from seconds
  const sec = src.poll_interval_sec;
  let num = sec / 60;
  let unit: "min" | "hr" = "min";
  if (sec % 3600 === 0) {
    num = sec / 3600;
    unit = "hr";
  }

  // Derive retention preset by matching hotDays + archivePolicy
  const PRESET_MAP: Record<
    string,
    { hotDays: number; archivePolicy: string }
  > = {
    short: { hotDays: 7, archivePolicy: "keep" },
    standard: { hotDays: 30, archivePolicy: "drop" },
    long: { hotDays: 90, archivePolicy: "move-to-cold" },
    "archive-only": { hotDays: 1, archivePolicy: "move-to-cold" },
  };
  const match = Object.keys(PRESET_MAP).find(
    (k) =>
      PRESET_MAP[k].hotDays === src.hot_retention_days &&
      PRESET_MAP[k].archivePolicy === src.archive_policy,
  );

  // Quick task 260425-ovt: prefill flattened scrape_* fields from initialSource.
  const sc = src.scrape_config ?? null;

  // The form schema only accepts the user-creatable subset of feed types;
  // legacy/internal types (bbot, brand-monitor) fall back to "rss" so the form
  // still mounts cleanly when an admin views such a source.
  const supportedFeedType: SourceFormValues["feed_type"] =
    src.feed_type === "rss" || src.feed_type === "taxii"
    || src.feed_type === "nvd" || src.feed_type === "custom"
      ? src.feed_type
      : "rss";

  return {
    name: src.name,
    feed_type: supportedFeedType,
    url: src.url,
    poll_interval_number: num,
    poll_interval_unit: unit,
    retention_preset: (match as SourceFormValues["retention_preset"]) ?? "custom",
    hot_retention_days_custom: src.hot_retention_days,
    archive_policy_custom: src.archive_policy,
    taxii_scheme: "none",
    enabled: src.enabled,
    scrape_item_selector: sc?.item_selector ?? "",
    scrape_title_selector: sc?.title_selector ?? "",
    scrape_link_selector: sc?.link_selector ?? "",
    scrape_date_selector: sc?.date_selector ?? "",
    scrape_date_format: sc?.date_format ?? "",
    scrape_summary_selector: sc?.summary_selector ?? "",
    scrape_max_items: sc?.max_items,
    // Quick task 260426-aas: derive mode from saved row. Pre-260426 rows have
    // selectors but no `mode` key — show those as Manual to preserve operator
    // mental model.
    scrape_mode:
      sc?.mode === "auto"
        ? "auto"
        : sc?.mode === "manual"
        ? "manual"
        : "manual",
  };
}

/**
 * Add/Edit Source Dialog.
 *
 * - Add mode: heading "Add Source", submit "Save Source"
 * - Edit mode: heading "Edit Source", submit "Save Changes", Type locked,
 * credential inputs show "(unchanged — type to replace)" placeholder
 *
 * Test Connection button is NON-BLOCKING: Save button is never disabled by
 * test result. Probe failure shows amber alert with exact copy:
 * "Test failed: {error_detail}. You can still save this configuration."
 * Probe success shows green alert:
 * "Connection OK · {latency_ms}ms · {item_count_sampled} items sampled"
*/
export function SourceDialog({
  open,
  mode,
  initialSource,
  onSubmit,
  onClose,
}: Props) {
  const form = useForm<SourceFormValues>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(baseSourceFormSchema) as any,
    defaultValues: defaultValuesFor(mode, initialSource) as SourceFormValues,
  });

  const {
    handleSubmit,
    formState: { errors, dirtyFields },
    watch,
    register,
    setValue,
    reset,
  } = form;

  // Reset form when dialog opens or mode/source changes so edit mode
  // reflects the correct prefilled values (not the initial-mount defaults).
  // This is needed because SourceDialog is always mounted (not conditionally
  // rendered) and useForm only initializes once at mount time.
  const prevOpenRef = useRef(false);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      reset(defaultValuesFor(mode, initialSource) as SourceFormValues);
      setTestResult(null);
    }
    prevOpenRef.current = open;
  }, [open, mode, initialSource, reset]);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestState>(null);
  const [templates, setTemplates] = useState<SourceTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string>("");

  // Fetch templates once on first mount (Add mode only).
  useEffect(() => {
    if (mode !== "add") return;
    let cancelled = false;
    fetchSourceTemplates()
      .then((t) => { if (!cancelled) setTemplates(t); })
      .catch(() => { /* silent — operator can fill form manually*/ });
    return () => { cancelled = true; };
  }, [mode]);

  function applyTemplate(id: string) {
    setTemplateId(id);
    if (!id) return;
    const tpl = templates.find((t) => t.id === id);
    if (!tpl) return;
    // Prefill name, feed_type, url, poll interval. Do NOT overwrite
    // credentials — operator fills their own. TAXII auth scheme set to
    // otx-apikey when template declares it.
    reset({
      ...defaultValuesFor("add"),
      name: tpl.name,
      feed_type: tpl.feed_type as "rss" | "taxii" | "nvd",
      url: tpl.url,
      poll_interval_number: Math.max(1, Math.round(tpl.poll_interval_sec / 60)),
      poll_interval_unit: tpl.poll_interval_sec >= 3600 ? "hr" : "min",
      taxii_scheme: tpl.auth_scheme === "otx-apikey" ? "otx-apikey"
                  : tpl.auth_scheme === "basic" ? "basic"
                  : tpl.auth_scheme === "bearer" ? "bearer"
                  : "none",
    } as SourceFormValues);
  }

  const feedType = watch("feed_type");

  async function runTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const values = form.getValues();
      const res = await testConnection({
        feed_type: values.feed_type,
        url: values.url,
        credentials: buildCredentialsDict(values) ?? null,
        ...(values.feed_type === "custom"
          ? { scrape_config: buildScrapeConfig(values) ?? null }
          : {}),
      });
      if (res.ok) {
        setTestResult({
          kind: "ok",
          latency_ms: res.latency_ms,
          item_count_sampled: res.item_count_sampled,
        });
      } else {
        setTestResult({
          kind: "fail",
          error_detail: res.error_detail ?? "unknown error",
        });
      }
    } catch (e) {
      setTestResult({
        kind: "fail",
        error_detail: (e as Error).message,
      });
    } finally {
      setTesting(false);
    }
  }

  async function onSubmitForm(values: SourceFormValues) {
    if (mode === "add") {
      await onSubmit(buildCreatePayload(values));
    } else {
      const credentialsTouched = Boolean(
        dirtyFields.taxii_username ||
          dirtyFields.taxii_password ||
          dirtyFields.taxii_token ||
          dirtyFields.nvd_api_key,
      );
      await onSubmit(buildUpdatePayload(values, credentialsTouched));
    }
  }

  const title = mode === "add" ? "Add Source" : "Edit Source";
  const submitLabel = mode === "add" ? "Save Source" : "Save Changes";

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-h-[90vh] flex flex-col p-0 gap-0">
        <FormProvider {...form}>
          <form
            onSubmit={handleSubmit(onSubmitForm)}
            className="flex flex-col min-h-0 flex-1"
          >
            <DialogHeader className="px-6 pt-6 pb-4 border-b shrink-0">
              <DialogTitle>{title}</DialogTitle>
            </DialogHeader>

            <div className="flex flex-col gap-4 overflow-y-auto px-6 py-4 min-h-0 flex-1">

            {/* Quick-add template picker — only visible in Add mode, hidden if no templates*/}
            {mode === "add" && templates.length > 0 && (
              <div className="flex flex-col gap-1">
                <Label htmlFor="template">Quick-add preset</Label>
                <Select
                  value={templateId}
                  onValueChange={applyTemplate}
                >
                  <SelectTrigger id="template">
                    <SelectValue placeholder="Select a preset or fill manually…" />
                  </SelectTrigger>
                  <SelectContent>
                    {templates.map((t) => (
                      <SelectItem key={t.id} value={t.id}>
                        {t.name} — {t.feed_type.toUpperCase()}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {templateId && (() => {
                  const tpl = templates.find((t) => t.id === templateId);
                  if (!tpl) return null;
                  return (
                    <span className="text-xs text-muted-foreground mt-1">
                      {tpl.description}
                      {tpl.credential_fields.length > 0 && (
                        <> Enter the required credentials below.</>
                      )}
                    </span>
                  );
                })()}
              </div>
            )}

            {/* Field 1: Name*/}
            <div className="flex flex-col gap-1">
              <Label htmlFor="name">Name</Label>
              <Input id="name" {...register("name")} />
              {errors.name && (
                <span className="text-xs text-destructive">
                  {errors.name.message}
                </span>
              )}
            </div>

            {/* Field 2: Type (locked on edit —)*/}
            <div className="flex flex-col gap-1">
              <Label htmlFor="feed_type">Type</Label>
              <Select
                value={feedType}
                onValueChange={(v) =>
                  setValue(
                    "feed_type",
                    v as "rss" | "taxii" | "nvd" | "custom",
                    { shouldDirty: true },
                  )
                }
                disabled={mode === "edit"}
              >
                <SelectTrigger id="feed_type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="rss">RSS</SelectItem>
                  <SelectItem value="taxii">TAXII</SelectItem>
                  <SelectItem value="nvd">NVD</SelectItem>
                  <SelectItem value="custom">Custom (HTML scrape)</SelectItem>
                </SelectContent>
              </Select>
              {mode === "edit" && (
                <span className="text-xs text-muted-foreground">
                  Feed type cannot be changed after creation.
                </span>
              )}
              {errors.feed_type && (
                <span className="text-xs text-destructive">
                  {errors.feed_type.message}
                </span>
              )}
            </div>

            {/* Field 3: URL*/}
            <div className="flex flex-col gap-1">
              <Label htmlFor="url">URL</Label>
              <Input id="url" type="url" {...register("url")} />
              {errors.url && (
                <span className="text-xs text-destructive">
                  {errors.url.message}
                </span>
              )}
            </div>

            {/* Field 4: Credentials (type-aware,)*/}
            <CredentialsField feed_type={feedType} mode={mode} />

            {/* Quick task 260425-ovt: HTML scrape selectors when feed_type='custom'*/}
            {feedType === "custom" && <HtmlScrapeFields mode={mode} />}

            {/* Field 5: Poll interval*/}
            <div className="flex flex-col gap-1">
              <Label htmlFor="poll_interval_number">Poll interval</Label>
              <div className="flex gap-2">
                <Input
                  id="poll_interval_number"
                  type="number"
                  min={1}
                  className="w-28"
                  {...register("poll_interval_number")}
                />
                <Select
                  value={watch("poll_interval_unit") ?? "min"}
                  onValueChange={(v) =>
                    setValue("poll_interval_unit", v as "min" | "hr", {
                      shouldDirty: true,
                    })
                  }
                >
                  <SelectTrigger className="w-28">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="min">minutes</SelectItem>
                    <SelectItem value="hr">hours</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {errors.poll_interval_number && (
                <span className="text-xs text-destructive">
                  {errors.poll_interval_number.message}
                </span>
              )}
            </div>

            {/* Fields 6–7: Retention preset (includes hot_retention_days + archive_policy for Custom)*/}
            <RetentionPresetPicker />

            {/* Test Connection inline result — NON-BLOCKING*/}
            {testResult?.kind === "ok" && (
              <Alert className="border-green-700 bg-green-900/20 text-green-300">
                <AlertDescription>
                  Connection OK &middot; {testResult.latency_ms}ms &middot;{" "}
                  {testResult.item_count_sampled} items sampled
                </AlertDescription>
              </Alert>
            )}
            {testResult?.kind === "fail" && (
              <Alert className="border-yellow-700 bg-yellow-900/20 text-yellow-300">
                <AlertDescription>
                  Test failed: {testResult.error_detail}. You can still save
                  this configuration.
                </AlertDescription>
              </Alert>
            )}

            </div>

            <DialogFooter className="flex gap-2 px-6 py-4 border-t shrink-0">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              {/* Test Connection: type="button" so it never submits the form.
 Brand: Primary teal outline — secondary action*/}
              <Button
                type="button"
                variant="outline"
                onClick={runTest}
                disabled={testing}
                style={{
                  borderColor: "var(--brand-primary)",
                  color: "var(--brand-primary)",
                }}
              >
                {testing ? "Testing connection..." : "Test Connection"}
              </Button>
              {/* Save button — NEVER disabled by test result.
 Brand: Signal amber — primary CTA*/}
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
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
}
