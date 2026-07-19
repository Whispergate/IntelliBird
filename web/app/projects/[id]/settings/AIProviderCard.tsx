"use client";

/**
 * AIProviderCard - Project AI Provider settings form (AI-01).
 * Surface 4 per 17-UI-SPEC.md.
 *
 * Form fields: provider Select, model_name Input, API key Input (hidden for Ollama),
 * AI rerank Switch, AI digest Switch, daily token cap Number Input.
 *
 * Inline Ollama health alert below provider Select when provider=ollama and
 * ollamaHealth is 'slow' or 'down'.
 *
 * Test connection: POST /api/projects/{id}/ai-provider/test
 * Save: PUT /api/projects/{id}/ai-provider
 *
 * Role gating: entire card visible to Admin only (caller must enforce).
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ProviderType = "ollama" | "openai" | "anthropic";
type OllamaHealth = "healthy" | "slow" | "down" | "unknown";

interface AIProviderRead {
  id: string;
  project_id: string;
  provider_type: ProviderType;
  model_name: string;
  api_base: string | null;
  api_key_masked: string | null; // '••••••••' or null
  ai_rerank_enabled: boolean;
  ai_digest_enabled: boolean;
  ai_daily_token_cap: number;
  digest_schedule_cron: string;
  created_at: string;
  updated_at: string;
}

interface Props {
  projectId: string;
  ollamaHealth?: OllamaHealth;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AIProviderCard({ projectId, ollamaHealth = "unknown" }: Props) {
  const [provider, setProvider] = useState<ProviderType>("ollama");
  const [modelName, setModelName] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiKeyMasked, setApiKeyMasked] = useState<string | null>(null);
  const [aiRerankEnabled, setAiRerankEnabled] = useState(false);
  const [aiDigestEnabled, setAiDigestEnabled] = useState(false);
  const [dailyTokenCap, setDailyTokenCap] = useState(100_000);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  // Load existing config on mount
  useEffect(() => {
    async function loadConfig() {
      try {
        const res = await fetch(`/api/projects/${projectId}/ai-provider`, {
          credentials: "include",
        });
        if (res.status === 404) {
          // No config yet - keep defaults
          return;
        }
        if (!res.ok) return;
        const data: AIProviderRead = await res.json();
        setProvider(data.provider_type);
        setModelName(data.model_name);
        setApiBase(data.api_base ?? "");
        setApiKeyMasked(data.api_key_masked);
        setAiRerankEnabled(data.ai_rerank_enabled);
        setAiDigestEnabled(data.ai_digest_enabled);
        setDailyTokenCap(data.ai_daily_token_cap);
      } catch {
        // Non-fatal - form keeps defaults
      }
    }
    loadConfig();
  }, [projectId]);

  // When provider changes, clear the API key field if switching away from cloud
  function handleProviderChange(value: ProviderType) {
    setProvider(value);
    if (value === "ollama") {
      // Clear API key when switching to Ollama
      setApiKey("");
    }
  }

  async function handleSave() {
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        provider_type: provider,
        model_name: modelName,
        ai_rerank_enabled: aiRerankEnabled,
        ai_digest_enabled: aiDigestEnabled,
        ai_daily_token_cap: dailyTokenCap,
      };
      if (provider === "ollama" && apiBase) {
        body.api_base = apiBase;
      }
      // Only include api_key if user typed a new one
      if (provider !== "ollama" && apiKey) {
        body.api_key = apiKey;
      }

      const res = await fetch(`/api/projects/${projectId}/ai-provider`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = "";
        try {
          const err = await res.json();
          detail = err.detail ?? err.message ?? "";
        } catch {
          detail = await res.text().catch(() => "");
        }
        toast.error(`Could not save AI settings. ${detail}`);
        return;
      }
      toast.success("AI settings saved.");
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not save AI settings. ${detail}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleTestConnection() {
    setTesting(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/ai-provider/test`, {
        method: "POST",
        credentials: "include",
      });
      if (res.ok) {
        toast.success("Connection successful.");
      } else {
        let detail = "";
        try {
          const err = await res.json();
          detail = err.detail ?? err.error ?? "";
        } catch {
          detail = await res.text().catch(() => "");
        }
        toast.error(`Connection failed: ${detail}`);
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Connection failed: ${detail}`);
    } finally {
      setTesting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="brand-heading">AI Provider</CardTitle>
        <p className="text-muted-foreground text-sm mt-1">
          Configure the LLM backend for event summarisation and digest.
        </p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4">
          {/* Provider Select */}
          <div>
            <Label htmlFor="ai-provider-type">Provider</Label>
            <Select value={provider} onValueChange={(v) => handleProviderChange(v as ProviderType)}>
              <SelectTrigger id="ai-provider-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ollama">Ollama</SelectItem>
                <SelectItem value="openai">OpenAI</SelectItem>
                <SelectItem value="anthropic">Anthropic</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Ollama health inline alert */}
          {provider === "ollama" && ollamaHealth === "slow" && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-yellow-600 bg-yellow-900/30 px-3 py-2 text-yellow-200 text-sm"
            >
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>
                Ollama responding slowly - phi3:mini or gemma2:2b recommended on CPU-only hosts.
              </span>
            </div>
          )}
          {provider === "ollama" && ollamaHealth === "down" && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-red-700 bg-red-900/30 px-3 py-2 text-red-200 text-sm"
            >
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <span>
                Ollama unreachable - run docker compose --profile ai up, or switch to OpenAI / Anthropic.
              </span>
            </div>
          )}

          {/* Model name */}
          <div>
            <Label htmlFor="ai-model-name">Model name</Label>
            <Input
              id="ai-model-name"
              type="text"
              placeholder="e.g. phi3:mini"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
            />
          </div>

          {/* Ollama API base */}
          {provider === "ollama" && (
            <div>
              <Label htmlFor="ai-api-base">Ollama API base URL</Label>
              <Input
                id="ai-api-base"
                type="text"
                placeholder="http://localhost:11434"
                value={apiBase}
                onChange={(e) => setApiBase(e.target.value)}
              />
            </div>
          )}

          {/* API key - only for cloud providers */}
          {provider !== "ollama" && (
            <div>
              <Label htmlFor="ai-api-key">API key</Label>
              <Input
                id="ai-api-key"
                type="password"
                placeholder={apiKeyMasked ?? "sk-…"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>
          )}

          {/* AI rerank switch */}
          <div className="flex items-start gap-3">
            <Switch
              id="ai-rerank"
              checked={aiRerankEnabled}
              onCheckedChange={setAiRerankEnabled}
            />
            <div>
              <Label htmlFor="ai-rerank">AI re-ranking</Label>
              <p className="text-muted-foreground text-xs mt-0.5">
                Adjusts rule scores by ±15 after nightly AI pass.
              </p>
            </div>
          </div>

          {/* AI digest switch */}
          <div className="flex items-start gap-3">
            <Switch
              id="ai-digest"
              checked={aiDigestEnabled}
              onCheckedChange={setAiDigestEnabled}
            />
            <div>
              <Label htmlFor="ai-digest">Daily digest</Label>
              <p className="text-muted-foreground text-xs mt-0.5">
                Generate a daily prose summary of top 10 events at 06:00 UTC.
              </p>
            </div>
          </div>

          {/* Daily token cap */}
          <div>
            <Label htmlFor="ai-token-cap">Daily token cap</Label>
            <Input
              id="ai-token-cap"
              type="number"
              min={1000}
              max={10_000_000}
              value={dailyTokenCap}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                setDailyTokenCap(isNaN(v) ? 100_000 : v);
              }}
            />
            <p className="text-muted-foreground text-xs mt-1">
              Resets at 00:00 UTC. Default: 100,000.
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between flex-wrap gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleTestConnection}
              disabled={testing}
            >
              {testing ? (
                <>
                  <Loader2 className="animate-spin mr-1" size={14} />
                  Testing…
                </>
              ) : (
                "Test connection"
              )}
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : "Save AI settings"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
