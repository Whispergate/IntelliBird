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

import {
  type FilterPreset,
  listPresets,
  testWebhook,
  type Webhook,
} from "@/app/api-client";
import { AuthField } from "./AuthField";
import { PresetMultiSelect } from "./PresetMultiSelect";
import {
  BATCHING_OPTIONS,
  DESTINATION_DEFAULT_URLS,
  buildCreatePayload,
  buildUpdatePayload,
  webhookFormSchema,
  type WebhookFormValues,
} from "../lib/webhookSchema";

type TestState =
  | { kind: "ok"; latency_ms: number }
  | { kind: "fail"; error_detail: string }
  | null;

type Props = {
  open: boolean;
  mode: "add" | "edit";
  initialWebhook?: Webhook;
  onSubmit: (
    payload:
      | ReturnType<typeof buildCreatePayload>
      | ReturnType<typeof buildUpdatePayload>,
  ) => void | Promise<void>;
  onClose: () => void;
};

function defaultValuesFor(
  mode: "add" | "edit",
  wh?: Webhook,
): Partial<WebhookFormValues> {
  if (mode === "add" || !wh) {
    return {
      destination_type: "slack",
      auth_type: "none",
      bound_preset_names: [],
      batching_window_sec: 300,
      enabled: true,
      email_use_starttls: true,
    };
  }
  return {
    name: wh.name,
    destination_type: wh.destination_type,
    url: wh.url,
    auth_type: "none", // always 'none' on open - operator re-enters to change
    bound_preset_names: wh.bound_preset_names,
    batching_window_sec: wh.batching_window_sec as 0 | 60 | 300 | 900 | 1800,
    enabled: wh.enabled,
    email_use_starttls: true,
  };
}

/**
 * Add/Edit Webhook Dialog.
 *
 * - Add mode: heading "Add Webhook", submit "Save Webhook"
 * - Edit mode: heading "Edit Webhook", submit "Save Changes", Type locked
 *
 * Test Send button is NON-BLOCKING: Save button is never disabled by
 * test result. Failure shows amber alert with exact copy:
 * "Test failed: {error_detail}. You can still save this configuration."
 * Success shows green alert:
 * "Test sent successfully · {latency}ms"
*/
export function WebhookDialog({
  open,
  mode,
  initialWebhook,
  onSubmit,
  onClose,
}: Props) {
  const form = useForm<WebhookFormValues>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(webhookFormSchema) as any,
    defaultValues: defaultValuesFor(mode, initialWebhook) as WebhookFormValues,
  });

  const {
    handleSubmit,
    formState: { errors, dirtyFields },
    watch,
    register,
    setValue,
    reset,
  } = form;

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestState>(null);
  const [presets, setPresets] = useState<FilterPreset[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(false);

  // Reset form and reload presets when dialog opens.
  // prevOpenRef tracks previous open state to only act on open transitions.
  const prevOpenRef = useRef(false);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      reset(defaultValuesFor(mode, initialWebhook) as WebhookFormValues);
      setTestResult(null);
      setPresetsLoading(true);
      listPresets()
        .then(setPresets)
        .catch(() => setPresets([]))
        .finally(() => setPresetsLoading(false));
    }
    prevOpenRef.current = open;
  }, [open, mode, initialWebhook, reset]);

  const destinationType = watch("destination_type");
  const boundPresetNames = watch("bound_preset_names") ?? [];
  const starttls = watch("email_use_starttls") ?? true;

  // Pre-fill URL when type changes to a type with a known default URL
  function handleTypeChange(v: string) {
    const next = v as WebhookFormValues["destination_type"];
    setValue("destination_type", next, { shouldDirty: true });
    const defaultUrl = DESTINATION_DEFAULT_URLS[next];
    if (defaultUrl !== undefined) {
      setValue("url", defaultUrl, { shouldDirty: true });
    }
  }

  async function runTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const values = form.getValues();
      const payload = buildCreatePayload(values);
      const res = await testWebhook({
        destination_type: values.destination_type,
        url: values.url,
        auth: payload.auth ?? null,
      });
      if (res.ok) {
        setTestResult({ kind: "ok", latency_ms: res.latency_ms });
      } else {
        setTestResult({
          kind: "fail",
          error_detail: res.error_detail ?? "unknown error",
        });
      }
    } catch (e) {
      setTestResult({ kind: "fail", error_detail: (e as Error).message });
    } finally {
      setTesting(false);
    }
  }

  async function onSubmitForm(values: WebhookFormValues) {
    if (mode === "add") {
      await onSubmit(buildCreatePayload(values));
    } else {
      const authTouched = Boolean(
        dirtyFields.auth_type ||
          dirtyFields.auth_token ||
          dirtyFields.auth_username ||
          dirtyFields.auth_password ||
          dirtyFields.auth_header_name ||
          dirtyFields.auth_header_value ||
          dirtyFields.email_from ||
          dirtyFields.email_to ||
          dirtyFields.email_username ||
          dirtyFields.email_password ||
          dirtyFields.email_use_starttls ||
          dirtyFields.pd_routing_key ||
          dirtyFields.opsgenie_api_key ||
          dirtyFields.ntfy_token,
      );
      await onSubmit(buildUpdatePayload(values, authTouched));
    }
  }

  const title = mode === "add" ? "Add Webhook" : "Edit Webhook";
  const submitLabel = mode === "add" ? "Save Webhook" : "Save Changes";

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <FormProvider {...form}>
          <form
            onSubmit={handleSubmit(onSubmitForm)}
            className="flex flex-col gap-4"
          >
            <DialogHeader>
              <DialogTitle>{title}</DialogTitle>
            </DialogHeader>

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

            {/* Field 2: Type - locked on edit*/}
            <div className="flex flex-col gap-1">
              <Label htmlFor="destination_type">Type</Label>
              <Select
                value={destinationType}
                onValueChange={handleTypeChange}
                disabled={mode === "edit"}
              >
                <SelectTrigger id="destination_type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="slack">Slack</SelectItem>
                  <SelectItem value="teams">Microsoft Teams</SelectItem>
                  <SelectItem value="discord">Discord</SelectItem>
                  <SelectItem value="generic">Generic JSON</SelectItem>
                  <SelectItem value="email">Email (SMTP)</SelectItem>
                  <SelectItem value="pagerduty">PagerDuty</SelectItem>
                  <SelectItem value="opsgenie">Opsgenie</SelectItem>
                  <SelectItem value="ntfy">ntfy</SelectItem>
                </SelectContent>
              </Select>
              {mode === "edit" && (
                <span className="text-xs text-muted-foreground">
                  Type cannot be changed after creation.
                </span>
              )}
              {errors.destination_type && (
                <span className="text-xs text-destructive">
                  {errors.destination_type.message}
                </span>
              )}
            </div>

            {/* Field 3: URL - label varies by type*/}
            <div className="flex flex-col gap-1">
              <Label htmlFor="url">
                {destinationType === "email"
                  ? "SMTP URL (smtp://host:587)"
                  : destinationType === "ntfy"
                  ? "Topic URL (e.g. https://ntfy.sh/my-topic)"
                  : "URL"}
              </Label>
              <Input id="url" type="url" {...register("url")} />
              {errors.url && (
                <span className="text-xs text-destructive">
                  {errors.url.message}
                </span>
              )}
            </div>

            {/* Field 4: Auth - conditional on Generic destination type*/}
            <AuthField />

            {/* Email credential fields */}
            {destinationType === "email" && (
              <div className="flex flex-col gap-2">
                <div className="flex gap-2">
                  <div className="flex-1 flex flex-col gap-1">
                    <Label htmlFor="email_from">From address</Label>
                    <Input
                      id="email_from"
                      type="email"
                      autoComplete="off"
                      placeholder="alerts@example.com"
                      {...register("email_from")}
                    />
                  </div>
                  <div className="flex-1 flex flex-col gap-1">
                    <Label htmlFor="email_to">To address</Label>
                    <Input
                      id="email_to"
                      type="email"
                      autoComplete="off"
                      placeholder="team@example.com"
                      {...register("email_to")}
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <div className="flex-1 flex flex-col gap-1">
                    <Label htmlFor="email_username">SMTP username</Label>
                    <Input
                      id="email_username"
                      autoComplete="off"
                      spellCheck={false}
                      {...register("email_username")}
                    />
                  </div>
                  <div className="flex-1 flex flex-col gap-1">
                    <Label htmlFor="email_password">SMTP password</Label>
                    <Input
                      id="email_password"
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      {...register("email_password")}
                    />
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    id="email_use_starttls"
                    type="checkbox"
                    checked={starttls}
                    onChange={(e) =>
                      setValue("email_use_starttls", e.target.checked, { shouldDirty: true })
                    }
                    className="h-4 w-4"
                  />
                  <Label htmlFor="email_use_starttls" className="cursor-pointer">
                    Use STARTTLS
                  </Label>
                </div>
              </div>
            )}

            {/* PagerDuty credential fields */}
            {destinationType === "pagerduty" && (
              <div className="flex flex-col gap-1">
                <Label htmlFor="pd_routing_key">Routing key</Label>
                <Input
                  id="pd_routing_key"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="R01234567890123456789012345678901"
                  {...register("pd_routing_key")}
                />
                {errors.pd_routing_key && (
                  <span className="text-xs text-destructive">
                    {errors.pd_routing_key.message}
                  </span>
                )}
              </div>
            )}

            {/* Opsgenie credential fields */}
            {destinationType === "opsgenie" && (
              <div className="flex flex-col gap-1">
                <Label htmlFor="opsgenie_api_key">API key</Label>
                <Input
                  id="opsgenie_api_key"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  {...register("opsgenie_api_key")}
                />
                {errors.opsgenie_api_key && (
                  <span className="text-xs text-destructive">
                    {errors.opsgenie_api_key.message}
                  </span>
                )}
                <span className="text-xs text-muted-foreground">
                  EU region: use https://api.eu.opsgenie.com/v2/alerts as URL above.
                </span>
              </div>
            )}

            {/* ntfy credential fields */}
            {destinationType === "ntfy" && (
              <div className="flex flex-col gap-1">
                <Label htmlFor="ntfy_token">Bearer token for private topics (optional)</Label>
                <Input
                  id="ntfy_token"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="tk_..."
                  {...register("ntfy_token")}
                />
              </div>
            )}

            {/* Field 5: Bound presets - async-loaded on open*/}
            <div className="flex flex-col gap-1">
              <Label>Bound presets</Label>
              <PresetMultiSelect
                value={boundPresetNames}
                options={presets}
                onChange={(names) =>
                  setValue("bound_preset_names", names, { shouldDirty: true })
                }
                loading={presetsLoading}
              />
            </div>

            {/* Field 6: Batching window*/}
            <div className="flex flex-col gap-1">
              <Label htmlFor="batching_window_sec">Batching window</Label>
              <Select
                value={String(watch("batching_window_sec") ?? 300)}
                onValueChange={(v) =>
                  setValue(
                    "batching_window_sec",
                    Number(v) as WebhookFormValues["batching_window_sec"],
                    { shouldDirty: true },
                  )
                }
              >
                <SelectTrigger id="batching_window_sec">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BATCHING_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={String(opt.value)}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Test Send inline alert - NON-BLOCKING*/}
            {testResult?.kind === "ok" && (
              <Alert className="border-green-700 bg-green-900/20 text-green-300">
                <AlertDescription>
                  Test sent successfully &middot; {testResult.latency_ms}ms
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

            <DialogFooter className="flex gap-2">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              {/* Test Send: type="button" so it never submits the form.
 Brand: Primary teal outline - secondary action*/}
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
                {testing ? "Sending..." : "Test Send"}
              </Button>
              {/* Save button - NEVER disabled by test result.
 Brand: Signal amber - primary CTA*/}
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
