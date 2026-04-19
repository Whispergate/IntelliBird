"use client";

import type { Webhook } from "@/app/api-client";

/**
 * Native confirm dialog for webhook deletion. verbatim copy.
 * No extra API call — the webhook object's bound_preset_names is already
 * populated by listWebhooks (join-hydrated in the router).
*/
export async function showDeleteConfirm(webhook: Webhook): Promise<boolean> {
  const n = webhook.bound_preset_names.length;
  const message =
    `Delete webhook "${webhook.name}"? ${n} bindings will be removed. ` +
    `No historical deliveries are tracked.`;
  return window.confirm(message);
}
