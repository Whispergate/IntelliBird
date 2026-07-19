"use client";

/**
 * /admin/ai-defaults - Global AI provider configuration.
 *
 * The LEGACY_PROJECT_ID (00000000-0000-0000-0000-000000000001) row in
 * `ai_providers` doubles as the system-wide default. New projects without
 * their own AIProvider row fall back to this configuration when
 * resolve_provider() runs in the worker. Editing here changes the model used
 * for any feed event ingested into _legacy as well as any project that has
 * not customised its provider.
 *
 * Reuses the existing per-project AIProviderCard component - same backend
 * endpoints (GET/PUT /api/projects/{id}/ai-provider, ollama-models dropdown,
 * test connection). Role-gated: Admin only (backend require_admin enforces).
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { AIProviderCard } from "@/app/projects/[id]/settings/AIProviderCard";

const LEGACY_PROJECT_ID = "00000000-0000-0000-0000-000000000001";

export default function AIDefaultsPage() {
  const router = useRouter();
  const { data: session, status } = useSession();

  useEffect(() => {
    if (status === "loading") return;
    const role = (session?.user as { role?: string } | undefined)?.role;
    if (role !== "Admin") router.replace("/");
  }, [session, status, router]);

  if (status === "loading") return null;
  const role = (session?.user as { role?: string } | undefined)?.role;
  if (role !== "Admin") return null;

  return (
    <div className="mx-auto max-w-2xl px-4 py-6">
      <div className="mb-4">
        <h1 className="brand-heading text-xl">Global AI Defaults</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Default LLM provider used for system-level AI tasks and as the fallback
          for projects without a per-project provider configured. Per-project
          overrides live under each project's Settings tab.
        </p>
      </div>
      <AIProviderCard projectId={LEGACY_PROJECT_ID} />
    </div>
  );
}
