import { z } from "zod";
import type {
  CreateWebhookPayload,
  UpdateWebhookPayload,
  DestinationType,
  WebhookAuth,
} from "@/app/api-client";

export const BATCHING_OPTIONS: { value: 0 | 60 | 300 | 900 | 1800; label: string }[] = [
  { value: 0,    label: "Immediate" },
  { value: 60,   label: "1 min" },
  { value: 300,  label: "5 min" },
  { value: 900,  label: "15 min" },
  { value: 1800, label: "30 min" },
];

// Default URLs pre-filled per destination type
export const DESTINATION_DEFAULT_URLS: Partial<Record<string, string>> = {
  pagerduty: "https://events.pagerduty.com/v2/enqueue",
  opsgenie:  "https://api.opsgenie.com/v2/alerts",
};

export const webhookFormSchema = z
  .object({
    name: z
      .string()
      .min(1, "Name is required")
      .max(64, "Name too long")
      .regex(/^[a-z0-9_-]{1,64}$/, "Lowercase letters, digits, hyphen, underscore only"),
    destination_type: z.enum([
      "slack", "teams", "discord", "generic",
      "email", "pagerduty", "opsgenie", "ntfy",
    ] as const),
    url: z.string().url("A valid URL is required"),
    auth_type: z.enum(["none", "bearer", "basic", "header"] as const).default("none"),
    auth_token: z.string().optional(),
    auth_username: z.string().optional(),
    auth_password: z.string().optional(),
    auth_header_name: z.string().optional(),
    auth_header_value: z.string().optional(),
    // Email-specific fields
    email_from: z.string().optional(),
    email_to: z.string().optional(),
    email_username: z.string().optional(),
    email_password: z.string().optional(),
    email_use_starttls: z.boolean().optional().default(true),
    // PagerDuty-specific fields
    pd_routing_key: z.string().optional(),
    // Opsgenie-specific fields
    opsgenie_api_key: z.string().optional(),
    // ntfy-specific fields
    ntfy_token: z.string().optional(),
    bound_preset_names: z.array(z.string()).default([]),
    batching_window_sec: z.union([
      z.literal(0),
      z.literal(60),
      z.literal(300),
      z.literal(900),
      z.literal(1800),
    ]).default(300),
    enabled: z.boolean().default(true),
  })
  .superRefine((data, ctx) => {
    if (data.destination_type === "generic" && data.auth_type === "bearer" && !data.auth_token) {
      ctx.addIssue({ code: "custom", path: ["auth_token"], message: "Token required" });
    }
    if (data.destination_type === "generic" && data.auth_type === "basic") {
      if (!data.auth_username)
        ctx.addIssue({ code: "custom", path: ["auth_username"], message: "Username required" });
      if (!data.auth_password)
        ctx.addIssue({ code: "custom", path: ["auth_password"], message: "Password required" });
    }
    if (data.destination_type === "generic" && data.auth_type === "header") {
      if (!data.auth_header_name)
        ctx.addIssue({ code: "custom", path: ["auth_header_name"], message: "Header name required" });
      if (!data.auth_header_value)
        ctx.addIssue({ code: "custom", path: ["auth_header_value"], message: "Header value required" });
    }
    if (data.destination_type === "pagerduty" && !data.pd_routing_key) {
      ctx.addIssue({ code: "custom", path: ["pd_routing_key"], message: "Routing key required" });
    }
    if (data.destination_type === "opsgenie" && !data.opsgenie_api_key) {
      ctx.addIssue({ code: "custom", path: ["opsgenie_api_key"], message: "API key required" });
    }
  });

export type WebhookFormValues = z.infer<typeof webhookFormSchema>;

function _authFromValues(v: WebhookFormValues): WebhookAuth | null {
  switch (v.destination_type) {
    case "generic":
      switch (v.auth_type) {
        case "bearer":
          return { type: "bearer", token: v.auth_token! };
        case "basic":
          return { type: "basic", username: v.auth_username!, password: v.auth_password! };
        case "header":
          return { type: "header", name: v.auth_header_name!, value: v.auth_header_value! };
        default:
          return null;
      }
    case "email":
      // Email credentials sent as JSON in auth_enc on the backend; mapped via bearer type
      // with a structured payload. Backend handles email-specific auth_enc shaping.
      return {
        type: "bearer",
        token: JSON.stringify({
          username: v.email_username ?? "",
          password: v.email_password ?? "",
          from_addr: v.email_from ?? "",
          to_addr: v.email_to ?? "",
          use_starttls: v.email_use_starttls ?? true,
        }),
      };
    case "pagerduty":
      return {
        type: "bearer",
        token: JSON.stringify({ routing_key: v.pd_routing_key ?? "" }),
      };
    case "opsgenie":
      return {
        type: "bearer",
        token: JSON.stringify({ type: "geniekey", api_key: v.opsgenie_api_key ?? "" }),
      };
    case "ntfy":
      if (!v.ntfy_token) return null;
      return {
        type: "bearer",
        token: JSON.stringify({ type: "bearer", token: v.ntfy_token }),
      };
    default:
      return null;
  }
}

// Phase 10: webhooks.project_id NOT NULL. Legacy sentinel bound by default
// until a project-picker lands on the webhooks UI.
const LEGACY_PROJECT_ID = "00000000-0000-0000-0000-000000000001";

export function buildCreatePayload(v: WebhookFormValues): CreateWebhookPayload {
  const auth = _authFromValues(v);
  return {
    name: v.name,
    project_id: LEGACY_PROJECT_ID,
    destination_type: v.destination_type as DestinationType,
    url: v.url,
    auth: auth ?? undefined,
    batching_window_sec: v.batching_window_sec,
    bound_preset_names: v.bound_preset_names,
    enabled: v.enabled,
  };
}

/**
 * Build the update payload. destination_type is DELIBERATELY ABSENT.
 * authTouched controls whether auth fields are sent:
 * - false → omit auth key (backend keeps existing)
 * - true + has auth → include auth object
 * - true + no auth → set clear_auth: true
*/
export function buildUpdatePayload(
  v: WebhookFormValues,
  authTouched: boolean,
): UpdateWebhookPayload {
  const payload: UpdateWebhookPayload = {
    name: v.name,
    url: v.url,
    batching_window_sec: v.batching_window_sec,
    bound_preset_names: v.bound_preset_names,
    enabled: v.enabled,
    // destination_type DELIBERATELY ABSENT
  };
  if (authTouched) {
    const auth = _authFromValues(v);
    if (auth) {
      payload.auth = auth;
    } else {
      payload.clear_auth = true;
    }
  }
  return payload;
}
