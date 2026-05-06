"use client";

/**
 * CTLogModeCard — Phase 32 / CERT-03.
 *
 * CT Log Mode selector for the Brand tab. Lead+ gated.
 * Three modes map to certstream_enabled boolean on the project:
 *   "crtsh"       → certstream_enabled = false  (existing 15-min crt.sh poll)
 *   "certstream"  → certstream_enabled = true   (CertStream live WebSocket)
 *   "both"        → certstream_enabled = true   (UI distinction; same backend flag)
 */

import { useState } from "react";
import { toast } from "sonner";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { updateProject } from "@/app/projects/lib/api";

type CTLogMode = "crtsh" | "certstream" | "both";

function modeFromFlag(certstreamEnabled: boolean | null | undefined): CTLogMode {
  return certstreamEnabled ? "certstream" : "crtsh";
}

interface CTLogModeCardProps {
  projectId: string;
  certstreamEnabled: boolean | null | undefined;
  isLead: boolean;
}

const MODE_LABELS: Record<CTLogMode, string> = {
  crtsh: "crt.sh (15 min)",
  certstream: "CertStream (live)",
  both: "Both",
};

export function CTLogModeCard({
  projectId,
  certstreamEnabled,
  isLead,
}: CTLogModeCardProps) {
  const [ctLogMode, setCtLogMode] = useState<CTLogMode>(
    modeFromFlag(certstreamEnabled),
  );
  const [saving, setSaving] = useState(false);

  if (!isLead) return null;

  async function handleCtLogModeChange(mode: CTLogMode) {
    setCtLogMode(mode);
    setSaving(true);
    try {
      await updateProject(projectId, {
        certstream_enabled: mode !== "crtsh",
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error.";
      toast.error(`Could not update CT Log Mode. ${msg}`);
      // Revert on error
      setCtLogMode(modeFromFlag(certstreamEnabled));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">CT Log Mode</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">
          CertStream provides sub-second certificate transparency alerts via
          WebSocket. crt.sh polls every 15 minutes.
        </p>
        <div className="flex gap-2 flex-wrap">
          {(["crtsh", "certstream", "both"] as const).map((mode) => (
            <Button
              key={mode}
              variant={ctLogMode === mode ? "default" : "outline"}
              size="sm"
              disabled={saving}
              onClick={() => handleCtLogModeChange(mode)}
            >
              {MODE_LABELS[mode]}
            </Button>
          ))}
        </div>
        {ctLogMode !== "crtsh" && (
          <Badge variant="secondary" className="text-xs">
            CertStream worker must be running — docker compose up
            certstream-worker
          </Badge>
        )}
      </CardContent>
    </Card>
  );
}
