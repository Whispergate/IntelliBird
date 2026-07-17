"use client";

/**
 * EASMGateForm — (UI-SPEC §Surface 2).
 *
 * Live two-factor active-scan gate form replacing 's read-only
 * EASMGatePreview scaffold. Rendered on the Settings tab.
 *
 * Two states:
 *   - Gate NOT set (active_scans_authorised=false):
 *       Field 1: type project name verbatim (scope_acknowledgement_text)
 *       Field 2: authorisation confirmation checkbox
 *       Submit: PATCH /api/projects/{id}/easm-gate
 *   - Gate IS set (active_scans_authorised=true):
 *       Status strip (green chip, confirmed-at, confirmed-by, TTL remaining)
 *       Revoke button (Lead/Admin only)
 *
 * Authority-matrix disabled states:
 *   - Observer/Contributor: all inputs disabled with muted caption
 *   - Legacy/archived project: all inputs disabled with muted caption
 *
 * 24h-remaining banner rendered ABOVE the card when gate IS set and
 * active_auth_confirmed_at > 6 days ago.
 *
 * Copy lock (UI-SPEC §Copywriting Contract — byte-exact):
 *   "Active-scan authorisation" (caption header)
 *   "Type the project name to confirm scope acknowledgement" (field 1 label)
 *   "Type project name exactly" (field 1 placeholder)
 *   "Project name does not match. Type it exactly as shown." (client error)
 *   "Scope acknowledgement text does not match the project name." (backend 422)
 *   "I confirm that written authorisation exists for active scans against this project's scope" (checkbox)
 *   "Authorise active scans" (submit)
 *   "Authorising…" (loading)
 *   "You do not have permission to authorise active scans. Lead or Admin role required." (403 toast)
 *   "Active scans authorised" (status chip)
 *   "Active-scan authorisation expires in less than 24 hours — re-confirm before launching more active scans." (24h banner)
 *   "Revoke authorisation" (revoke button)
 *   "Active-scan authorisation revoked." (revoke success toast)
 *   "Active-scan authorisation can only be set or revoked by a project Lead or global Admin." (Observer caption)
 *   "Authorisation is not available for archived or legacy projects." (legacy/archived caption)
 */

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EASMGateProject {
  id: string;
  name: string;
  archived: boolean;
  active_scans_authorised: boolean;
  scope_acknowledgement_text: string | null;
  active_auth_confirmed_at: string | null;
  active_auth_confirmed_by: string | null;
}

export interface EASMGateFormProps {
  project: EASMGateProject;
  isLegacy: boolean;
  userIsLeadOrAdmin: boolean;
  /** TTL in seconds. Default 604800 (7 days). */
  ttlSeconds?: number;
  onGateChanged: (updated: EASMGateProject) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEFAULT_TTL_SECONDS = 604800; // 7 days
const WARNING_THRESHOLD_MS = 6 * 24 * 60 * 60 * 1000; // 6 days

function formatTtlRemaining(msRemaining: number): {
  text: string;
  isAmber: boolean;
} {
  const oneDayMs = 24 * 60 * 60 * 1000;
  if (msRemaining <= oneDayMs) {
    const hours = Math.max(0, Math.floor(msRemaining / (60 * 60 * 1000)));
    return { text: `Expires in ${hours}h`, isAmber: true };
  }
  const days = Math.floor(msRemaining / (24 * 60 * 60 * 1000));
  const hours = Math.floor(
    (msRemaining % (24 * 60 * 60 * 1000)) / (60 * 60 * 1000),
  );
  return { text: `Expires in ${days}d ${hours}h`, isAmber: false };
}

function truncateSub(sub: string, maxLen = 24): string {
  if (sub.length <= maxLen) return sub;
  return sub.slice(0, maxLen) + "…";
}

function is24hWarningActive(
  confirmedAtIso: string | null,
  ttlSeconds: number,
): boolean {
  if (!confirmedAtIso) return false;
  const confirmedAt = new Date(confirmedAtIso).getTime();
  const now = Date.now();
  // Show warning when more than 6 days have elapsed (< 24h remaining in 7d TTL)
  return now - confirmedAt > WARNING_THRESHOLD_MS;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EASMGateForm({
  project,
  isLegacy,
  userIsLeadOrAdmin,
  ttlSeconds = DEFAULT_TTL_SECONDS,
  onGateChanged,
}: EASMGateFormProps) {
  const [ackText, setAckText] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [backendError, setBackendError] = useState<string | null>(null);

  const disabledByLegacy = isLegacy || project.archived;
  const disabledByAuthority = !userIsLeadOrAdmin;
  const isDisabled = disabledByLegacy || disabledByAuthority;

  const clientMismatch =
    ackText.length > 0 && ackText !== project.name;

  const submitEnabled =
    ackText === project.name &&
    confirmed &&
    !submitting &&
    !isDisabled;

  // 24h banner condition
  const show24hBanner =
    project.active_scans_authorised &&
    is24hWarningActive(project.active_auth_confirmed_at, ttlSeconds);

  // TTL remaining
  let ttlInfo: { text: string; isAmber: boolean } | null = null;
  if (project.active_scans_authorised && project.active_auth_confirmed_at) {
    const confirmedAt = new Date(project.active_auth_confirmed_at).getTime();
    const expiry = confirmedAt + ttlSeconds * 1000;
    const msRemaining = expiry - Date.now();
    ttlInfo = formatTtlRemaining(Math.max(0, msRemaining));
  }

  async function handleSubmit() {
    if (!submitEnabled) return;
    setSubmitting(true);
    setBackendError(null);
    try {
      const res = await fetch(`/api/projects/${project.id}/easm-gate`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope_acknowledgement_text: ackText,
          confirm_authorisation: true,
        }),
      });
      if (res.ok) {
        const updated = (await res.json()) as EASMGateProject;
        setAckText("");
        setConfirmed(false);
        onGateChanged(updated);
        return;
      }
      if (res.status === 403) {
        toast.error(
          "You do not have permission to authorise active scans. Lead or Admin role required.",
        );
        return;
      }
      if (res.status === 422) {
        let detail = "Scope acknowledgement text does not match the project name.";
        try {
          const data = await res.json();
          if (
            data &&
            typeof data === "object" &&
            "detail" in data &&
            typeof data.detail === "string"
          ) {
            if (
              String(data.detail)
                .toLowerCase()
                .includes("scope acknowledgement")
            ) {
              detail =
                "Scope acknowledgement text does not match the project name.";
            } else if (
              String(data.detail)
                .toLowerCase()
                .includes("archived") ||
              String(data.detail).toLowerCase().includes("legacy")
            ) {
              toast.error(
                "Authorisation is not available for archived or legacy projects.",
              );
              return;
            }
          }
        } catch {
          // ignore parse errors
        }
        setBackendError(detail);
        return;
      }
      toast.error("Could not authorise active scans. Please try again.");
    } catch {
      toast.error("Could not authorise active scans. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevoke() {
    const ok = window.confirm(
      `Revoke active-scan authorisation for "${project.name}"? Running active scans will complete but no new active scans can be launched until re-authorised.`,
    );
    if (!ok) return;
    try {
      const res = await fetch(`/api/projects/${project.id}/easm-gate`, {
        method: "DELETE",
      });
      if (res.ok) {
        const updated = (await res.json()) as EASMGateProject;
        toast.success("Active-scan authorisation revoked.");
        onGateChanged(updated);
        return;
      }
      toast.error("Could not revoke authorisation. Please try again.");
    } catch {
      toast.error("Could not revoke authorisation. Please try again.");
    }
  }

  return (
    <div className="space-y-3">
      {/* 24h-remaining amber banner — rendered ABOVE the card */}
      {show24hBanner && (
        <div
          className="border-l-4 border-[var(--brand-signal)] bg-accent/10 px-4 py-3 rounded-sm text-sm"
          role="alert"
        >
          Active-scan authorisation expires in less than 24 hours — re-confirm
          before launching more active scans.
        </div>
      )}

      {/* Gate card */}
      <div className="rounded-md border border-border bg-card p-4 space-y-4">
        {/* Caption header */}
        <div className="brand-caption text-muted-foreground">
          Active-scan authorisation
        </div>

        {/* Authority-matrix disabled captions */}
        {disabledByLegacy && (
          <p className="text-sm text-muted-foreground">
            Authorisation is not available for archived or legacy projects.
          </p>
        )}
        {!disabledByLegacy && disabledByAuthority && (
          <p className="text-sm text-muted-foreground">
            Active-scan authorisation can only be set or revoked by a project
            Lead or global Admin.
          </p>
        )}

        {/* Active-gate status strip (gate IS set) */}
        {project.active_scans_authorised && project.active_auth_confirmed_at && (
          <div className="space-y-1">
            {/* Green status chip */}
            <div className="inline-flex items-center rounded-full bg-primary/20 px-2.5 py-0.5 text-xs font-medium text-primary">
              Active scans authorised
            </div>
            <p className="text-sm text-foreground">
              Authorised:{" "}
              {new Date(project.active_auth_confirmed_at).toLocaleDateString(
                "en-GB",
                {
                  day: "2-digit",
                  month: "short",
                  year: "numeric",
                },
              )}{" "}
              {new Date(project.active_auth_confirmed_at).toLocaleTimeString(
                "en-GB",
                { hour: "2-digit", minute: "2-digit", hour12: false },
              )}{" "}
              UTC
            </p>
            {project.active_auth_confirmed_by && (
              <p
                className="text-sm text-muted-foreground"
                title={project.active_auth_confirmed_by}
              >
                by {truncateSub(project.active_auth_confirmed_by)}
              </p>
            )}
            {ttlInfo && (
              <p
                className={`text-sm ${ttlInfo.isAmber ? "text-[var(--brand-signal)]" : "text-muted-foreground"}`}
              >
                {ttlInfo.text}
              </p>
            )}
          </div>
        )}

        {/* Gate form — shown when gate NOT set, or always (user can re-confirm) */}
        {!project.active_scans_authorised && (
          <div className="space-y-4">
            {/* Field 1: scope acknowledgement text */}
            <div className="space-y-1">
              <Label htmlFor="easm-gate-ack">
                Type the project name to confirm scope acknowledgement
              </Label>
              <Input
                id="easm-gate-ack"
                value={ackText}
                onChange={(e) => {
                  setAckText(e.target.value);
                  setBackendError(null);
                }}
                placeholder="Type project name exactly"
                disabled={isDisabled}
                autoComplete="off"
              />
              {clientMismatch && !backendError && (
                <p className="text-destructive text-sm mt-1">
                  Project name does not match. Type it exactly as shown.
                </p>
              )}
              {backendError && (
                <p className="text-destructive text-sm mt-1">{backendError}</p>
              )}
            </div>

            {/* Field 2: authorisation checkbox */}
            <div className="flex items-start gap-2">
              <Checkbox
                id="easm-gate-confirm"
                checked={confirmed}
                onCheckedChange={(v) => setConfirmed(v === true)}
                disabled={isDisabled}
              />
              <Label
                htmlFor="easm-gate-confirm"
                className="cursor-pointer leading-snug"
              >
                I confirm that written authorisation exists for active scans
                against this project&apos;s scope
              </Label>
            </div>

            {/* Submit button */}
            <Button
              onClick={handleSubmit}
              disabled={!submitEnabled}
            >
              {submitting ? "Authorising…" : "Authorise active scans"}
            </Button>
          </div>
        )}

        {/* Revoke section (Lead/Admin only, gate IS set, not legacy/archived) */}
        {project.active_scans_authorised &&
          userIsLeadOrAdmin &&
          !isLegacy &&
          !project.archived && (
            <>
              <Separator />
              <Button variant="destructive" onClick={handleRevoke}>
                Revoke authorisation
              </Button>
            </>
          )}
      </div>
    </div>
  );
}
