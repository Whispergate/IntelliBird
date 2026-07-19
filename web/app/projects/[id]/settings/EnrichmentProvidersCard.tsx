"use client";

/**
 * EnrichmentProvidersCard - per-provider reputation API key config.
 * ENRICH-01, ENRICH-04.
 *
 * Mirrors AIProviderCard.tsx structure.
 * Lead+ role required to edit; all roles can read.
 *
 * - One row per provider (6 providers)
 * - Switch (enabled) + masked API key Input + optional daily_request_cap
 * - Circuit breaker badge when breaker_open_until is set
 * - OPSEC warning when any provider is enabled
 * - Role gate: card content is read-only for non-Lead roles
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Eye, EyeOff, AlertTriangle, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  listEnrichmentProviders,
  upsertEnrichmentProvider,
  type EnrichmentProviderRead,
  type EnrichmentProviderName,
  type EnrichmentProviderWrite,
} from "@/app/api-client";
import { useProjectRole } from "@/app/projects/[id]/ProjectRoleProvider";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PROVIDER_LABELS: Record<EnrichmentProviderName, string> = {
  vt: "VirusTotal",
  abuseipdb: "AbuseIPDB",
  greynoise: "GreyNoise",
  otx: "OTX AlienVault",
  shodan: "Shodan",
  urlhaus: "URLhaus",
};

const KEYLESS_PROVIDERS = new Set<EnrichmentProviderName>(["greynoise", "urlhaus"]);

const ALL_PROVIDERS: EnrichmentProviderName[] = [
  "vt",
  "abuseipdb",
  "greynoise",
  "otx",
  "shodan",
  "urlhaus",
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProviderRowState {
  enabled: boolean;
  apiKey: string;
  apiKeyMasked: string | null;
  dailyCap: string; // stored as string for input control; parsed on save
  breakerOpenUntil: string | null;
  saving: boolean;
  showKey: boolean;
}

type ProviderMap = Partial<Record<EnrichmentProviderName, ProviderRowState>>;

function defaultRow(): ProviderRowState {
  return {
    enabled: false,
    apiKey: "",
    apiKeyMasked: null,
    dailyCap: "",
    breakerOpenUntil: null,
    saving: false,
    showKey: false,
  };
}

function rowFromRead(r: EnrichmentProviderRead): ProviderRowState {
  return {
    enabled: r.enabled,
    apiKey: "",
    apiKeyMasked: r.api_key_masked,
    dailyCap: r.daily_request_cap !== null ? String(r.daily_request_cap) : "",
    breakerOpenUntil: r.breaker_open_until,
    saving: false,
    showKey: false,
  };
}

function formatBreakerTime(iso: string): string {
  try {
    return (
      new Date(iso).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }) + " UTC"
    );
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  projectId: string;
}

export function EnrichmentProvidersCard({ projectId }: Props) {
  const { isLead } = useProjectRole();
  const [rows, setRows] = useState<ProviderMap>({});
  const [loading, setLoading] = useState(true);

  // Load existing provider configs on mount
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await listEnrichmentProviders(projectId);
        if (cancelled) return;
        const map: ProviderMap = {};
        for (const r of data) {
          map[r.provider] = rowFromRead(r);
        }
        setRows(map);
      } catch {
        // Non-fatal - show defaults
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  function getRow(provider: EnrichmentProviderName): ProviderRowState {
    return rows[provider] ?? defaultRow();
  }

  function setRow(
    provider: EnrichmentProviderName,
    patch: Partial<ProviderRowState>,
  ) {
    setRows((prev) => ({
      ...prev,
      [provider]: { ...getRow(provider), ...patch },
    }));
  }

  async function handleSave(provider: EnrichmentProviderName) {
    const row = getRow(provider);
    setRow(provider, { saving: true });
    try {
      const payload: EnrichmentProviderWrite = {
        enabled: row.enabled,
        daily_request_cap: row.dailyCap !== "" ? Number(row.dailyCap) : null,
      };
      // Only send api_key if user typed a new one
      if (!KEYLESS_PROVIDERS.has(provider) && row.apiKey) {
        payload.api_key = row.apiKey;
      }
      const updated = await upsertEnrichmentProvider(projectId, provider, payload);
      setRow(provider, {
        saving: false,
        apiKey: "",
        apiKeyMasked: updated.api_key_masked,
        breakerOpenUntil: updated.breaker_open_until,
      });
      toast.success(`${PROVIDER_LABELS[provider]} settings saved.`);
    } catch (e) {
      const detail = e instanceof Error ? e.message : "Unknown error.";
      toast.error(`Could not save ${PROVIDER_LABELS[provider]} settings. ${detail}`);
      setRow(provider, { saving: false });
    }
  }

  const anyEnabled = ALL_PROVIDERS.some((p) => getRow(p).enabled);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="brand-heading">Enrichment Providers</CardTitle>
        <p className="text-muted-foreground text-sm mt-1">
          Configure external reputation APIs for IOC enrichment. Enable providers
          and paste API keys to automatically score indicators.
        </p>
      </CardHeader>
      <CardContent>
        {/* OPSEC warning - shown when any provider is enabled */}
        {anyEnabled && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-amber-600 bg-amber-900/20 px-3 py-2 text-amber-200 text-sm mb-4"
          >
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>
              Warning: data leaves perimeter when this provider is enabled. Ensure
              your threat intelligence operations policy permits external lookups.
            </span>
          </div>
        )}

        {loading ? (
          <div className="flex flex-col gap-4">
            {ALL_PROVIDERS.map((p) => (
              <div key={p} className="h-12 bg-muted rounded animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-6">
            {ALL_PROVIDERS.map((provider) => {
              const row = getRow(provider);
              const isKeyless = KEYLESS_PROVIDERS.has(provider);
              return (
                <div
                  key={provider}
                  className="flex flex-col gap-3 p-4 rounded-lg border border-border bg-card/40"
                >
                  {/* Row header: provider name + enabled switch + breaker badge */}
                  <div className="flex items-center gap-3">
                    <Switch
                      id={`enrich-${provider}-enabled`}
                      checked={row.enabled}
                      onCheckedChange={(v) => setRow(provider, { enabled: v })}
                      disabled={!isLead}
                      aria-label={`Enable ${PROVIDER_LABELS[provider]}`}
                    />
                    <Label
                      htmlFor={`enrich-${provider}-enabled`}
                      className="text-sm font-medium cursor-pointer"
                    >
                      {PROVIDER_LABELS[provider]}
                    </Label>
                    {row.breakerOpenUntil && (
                      <Badge variant="destructive" className="ml-auto flex items-center gap-1 text-xs">
                        <ShieldAlert size={12} />
                        Breaker open until {formatBreakerTime(row.breakerOpenUntil)}
                      </Badge>
                    )}
                  </div>

                  {/* API key input - hidden for keyless providers */}
                  {isKeyless ? (
                    <p className="text-xs text-muted-foreground">
                      (no API key required for free tier)
                    </p>
                  ) : (
                    <div className="flex flex-col gap-1">
                      <Label
                        htmlFor={`enrich-${provider}-key`}
                        className="text-xs text-muted-foreground"
                      >
                        API key
                      </Label>
                      <div className="relative flex items-center">
                        <Input
                          id={`enrich-${provider}-key`}
                          type={row.showKey ? "text" : "password"}
                          placeholder={row.apiKeyMasked ?? "Paste API key…"}
                          value={row.apiKey}
                          onChange={(e) => setRow(provider, { apiKey: e.target.value })}
                          disabled={!isLead}
                          className="pr-10"
                        />
                        <button
                          type="button"
                          className="absolute right-2 text-muted-foreground hover:text-foreground transition-colors"
                          onClick={() => setRow(provider, { showKey: !row.showKey })}
                          aria-label={row.showKey ? "Hide API key" : "Show API key"}
                          tabIndex={-1}
                        >
                          {row.showKey ? <EyeOff size={15} /> : <Eye size={15} />}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Daily request cap */}
                  <div className="flex flex-col gap-1">
                    <Label
                      htmlFor={`enrich-${provider}-cap`}
                      className="text-xs text-muted-foreground"
                    >
                      Daily request cap
                    </Label>
                    <Input
                      id={`enrich-${provider}-cap`}
                      type="number"
                      min={1}
                      max={100_000}
                      placeholder="Unlimited"
                      value={row.dailyCap}
                      onChange={(e) => setRow(provider, { dailyCap: e.target.value })}
                      disabled={!isLead}
                      className="max-w-[160px]"
                    />
                  </div>

                  {/* Save button - Lead+ only */}
                  {isLead && (
                    <div className="flex justify-end">
                      <Button
                        size="sm"
                        onClick={() => void handleSave(provider)}
                        disabled={row.saving}
                      >
                        {row.saving ? "Saving…" : `Save ${PROVIDER_LABELS[provider]}`}
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
