import type { Webhook } from "../api-client";
import { listWebhooks } from "../api-client";
import { WebhooksClient } from "./WebhooksClient";

export default async function WebhooksPage() {
  let webhooks: Webhook[] = [];
  try {
    webhooks = await listWebhooks();
  } catch {
    webhooks = [];
  }
  return <WebhooksClient initialWebhooks={webhooks} />;
}
