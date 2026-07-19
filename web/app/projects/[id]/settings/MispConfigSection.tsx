"use client";

/**
 * MispConfigSection - MISP-01.
 *
 * MISP integration configuration card for Project Settings.
 * Lead+ gated (caller passes isLead prop).
 *
 * Features:
 *  - URL field + masked API key input
 *  - Pull tags multi-input (Enter or Add button)
 *  - Push types checkboxes (CVE / ATT&CK / Actor)
 *  - Enable MISP sync toggle
 *  - Verify TLS certificate toggle
 *  - Save (PUT / PATCH) + Test Connection button with inline result
 */

import { useState, useEffect } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  getMispConfig,
  upsertMispConfig,
  patchMispConfig,
  testMispConnection,
  type MispConfigRead,
} from "@/app/api-client";

interface MispConfigSectionProps {
  projectId: string;
  isLead: boolean;
}

const PUSH_TYPE_OPTIONS = [
  { value: "cve", label: "CVE" },
  { value: "attack", label: "ATT&CK Technique" },
  { value: "actor", label: "Threat Actor" },
] as const;

export function MispConfigSection({ projectId, isLead }: MispConfigSectionProps) {
  const [config, setConfig] = useState<MispConfigRead | null>(null);
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [pullTags, setPullTags] = useState<string[]>([]);
  const [pullTagInput, setPullTagInput] = useState("");
  const [pushTypes, setPushTypes] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [sslVerify, setSslVerify] = useState(true);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    version?: string;
    error?: string;
  } | null>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getMispConfig(projectId)
      .then((cfg) => {
        setConfig(cfg);
        setUrl(cfg.url);
        setPullTags(cfg.pull_tags);
        setPushTypes(cfg.push_types);
        setEnabled(cfg.enabled);
        setSslVerify(cfg.ssl_verify);
      })
      .catch(() => {
        // 404 = no config yet; start with empty form
      });
  }, [projectId]);

  async function handleSave() {
    setSaving(true);
    try {
      // If existing config and no new API key entered, use PATCH (avoids
      // requiring re-entry of the key on every save)
      const saved =
        config && !apiKey
          ? await patchMispConfig(projectId, {
              url: url || undefined,
              pull_tags: pullTags,
              push_types: pushTypes,
              enabled,
              ssl_verify: sslVerify,
            })
          : await upsertMispConfig(projectId, {
              url,
              api_key: apiKey,
              pull_tags: pullTags,
              push_types: pushTypes,
              enabled,
              ssl_verify: sslVerify,
            });
      setConfig(saved);
      setApiKey(""); // clear after save - backend stores encrypted copy
    } catch (err) {
      console.error("MISP save failed", err);
    } finally {
      setSaving(false);
    }
  }

  async function handleTestConnection() {
    if (!url || !apiKey) return;
    setTestLoading(true);
    setTestResult(null);
    try {
      const result = await testMispConnection(projectId, {
        url,
        api_key: apiKey,
        ssl_verify: sslVerify,
      });
      setTestResult(result);
    } catch {
      setTestResult({ ok: false, error: "Request failed" });
    } finally {
      setTestLoading(false);
    }
  }

  function addPullTag() {
    const tag = pullTagInput.trim();
    if (tag && !pullTags.includes(tag)) {
      setPullTags([...pullTags, tag]);
    }
    setPullTagInput("");
  }

  function togglePushType(type: string) {
    setPushTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  }

  if (!isLead) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">MISP Integration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <Label htmlFor="misp-url">MISP URL</Label>
          <Input
            id="misp-url"
            placeholder="https://misp.example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="misp-key">
            API Key{config ? " (leave blank to keep current)" : ""}
          </Label>
          <Input
            id="misp-key"
            type="password"
            placeholder={config ? "••••••••" : "Enter MISP API key"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label>Pull Tags</Label>
          <div className="flex gap-2">
            <Input
              placeholder="e.g. tlp:white"
              value={pullTagInput}
              onChange={(e) => setPullTagInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addPullTag()}
            />
            <Button variant="outline" size="sm" onClick={addPullTag}>
              Add
            </Button>
          </div>
          <div className="flex flex-wrap gap-1 mt-1">
            {pullTags.map((tag) => (
              <Badge
                key={tag}
                variant="secondary"
                className="cursor-pointer"
                onClick={() => setPullTags(pullTags.filter((t) => t !== tag))}
              >
                {tag} ×
              </Badge>
            ))}
          </div>
        </div>
        <div className="space-y-2">
          <Label>Push to MISP on confirmation</Label>
          <p className="text-xs text-muted-foreground">
            Selected suggestion types will be pushed to MISP as proposals when
            confirmed.
          </p>
          {PUSH_TYPE_OPTIONS.map(({ value, label }) => (
            <div key={value} className="flex items-center gap-2">
              <Checkbox
                id={`push-${value}`}
                checked={pushTypes.includes(value)}
                onCheckedChange={() => togglePushType(value)}
              />
              <Label htmlFor={`push-${value}`} className="font-normal">
                {label}
              </Label>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="misp-enabled"
            checked={enabled}
            onCheckedChange={setEnabled}
          />
          <Label htmlFor="misp-enabled">Enable MISP sync</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="misp-ssl"
            checked={sslVerify}
            onCheckedChange={setSslVerify}
          />
          <Label htmlFor="misp-ssl">Verify TLS certificate</Label>
        </div>
        <div className="flex gap-2 pt-2">
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button
            variant="outline"
            onClick={handleTestConnection}
            disabled={testLoading || !url || !apiKey}
          >
            {testLoading ? "Testing…" : "Test Connection"}
          </Button>
        </div>
        {testResult && (
          <div
            className={`text-sm p-2 rounded ${
              testResult.ok
                ? "bg-green-50 text-green-800"
                : "bg-red-50 text-red-800"
            }`}
          >
            {testResult.ok
              ? `Connected - MISP ${testResult.version ?? ""}`
              : `Failed: ${testResult.error}`}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
