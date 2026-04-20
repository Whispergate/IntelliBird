"use client";

/**
 * ProjectCompareClient — client component for /projects/compare.
 *
 * Contract (locked by .planning/phases/10-projects-foundation/10-UI-SPEC.md
 * §/projects/compare and 10-13-PLAN.md §must_haves):
 *
 *   - Two project picker Selects (A and B) defaulting to the `a` + `b` query
 *     params. Archived projects are filtered out of the picker options (the
 *     user can still compare an archived project by deep-linking with ?a/?b,
 *     but the picker only surfaces active projects).
 *   - Swap button between the pickers toggles the `a` and `b` query params
 *     via router.replace — aids the mental model when operators want to
 *     invert the direction.
 *   - When BOTH `a` and `b` are present in the query, fire
 *     `compareProjects(a, b)` via useEffect and render three CompareTable
 *     panels: Shared actors / Shared techniques / Shared IOCs.
 *   - Row affordances:
 *       Actor  → link to /events?stix_type=threat-actor&actor=<name>
 *       Tech   → link to https://attack.mitre.org/techniques/<id>/
 *       IOC    → copy-to-clipboard button (keyboard accessible)
 *   - Empty section → single muted line with UI-SPEC copy.
 *   - 500-row cap caption when length === 500 (CAP constant).
 *
 * Failure modes:
 *   - Fetch failure → sonner toast "Could not load comparison. <msg>"; clears
 *     the previous result so stale rows never linger.
 *   - 404 (one of the projects missing / user lacks access) → same toast path;
 *     backend's detail string surfaces as the `<msg>` suffix.
 */

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRightLeft, Copy, ExternalLink } from "lucide-react";
import { toast } from "sonner";

import type { CompareResponse, ProjectResponse, SharedIOC } from "../lib/api";
import { compareProjects } from "../lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CompareTable, copyToClipboard } from "./components/CompareTable";

// 500-row per-section cap — mirrors COMPARE_CAP on the backend
// (backend/app/services/project_compare.py). Length === CAP is the signal to
// render the truncation caption; we can't distinguish length === CAP from
// "real" 500 without a separate COUNT(*) round-trip, so the UI-SPEC's
// "CLAUDE DISCRETION" lock says: length === 500 → show caption.
const CAP = 500;

export function ProjectCompareClient({
  projects,
}: {
  projects: ProjectResponse[];
}) {
  const router = useRouter();
  const sp = useSearchParams();
  const a = sp.get("a") ?? "";
  const b = sp.get("b") ?? "";

  const [result, setResult] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!a || !b) {
      setResult(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    compareProjects(a, b)
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "Unknown error";
        toast.error(`Could not load comparison. ${msg}`);
        setResult(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [a, b]);

  function pushParams(p: URLSearchParams) {
    const qs = p.toString();
    router.replace(qs ? `/projects/compare?${qs}` : "/projects/compare");
  }

  function setSide(side: "a" | "b", projectId: string) {
    const p = new URLSearchParams(sp);
    if (projectId) p.set(side, projectId);
    else p.delete(side);
    pushParams(p);
  }

  function swap() {
    // Noop if neither side is set.
    if (!a && !b) return;
    const p = new URLSearchParams(sp);
    if (b) p.set("a", b);
    else p.delete("a");
    if (a) p.set("b", a);
    else p.delete("b");
    pushParams(p);
  }

  const pickerOptions = projects.filter((p) => !p.archived);

  return (
    <div className="space-y-8">
      <header>
        <h1 className="brand-display text-foreground">Compare projects</h1>
        <p className="text-muted-foreground mt-1">
          Shared actors, techniques, and IOCs between two projects.
        </p>
      </header>

      <div className="flex items-center gap-3">
        <div className="flex-1">
          <label className="brand-caption text-muted-foreground block mb-1">
            Project A
          </label>
          <Select
            value={a || undefined}
            onValueChange={(v) => setSide("a", v)}
          >
            <SelectTrigger aria-label="Project A">
              <SelectValue placeholder="Pick project A…" />
            </SelectTrigger>
            <SelectContent>
              {pickerOptions.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col items-center">
          {/* Spacer to visually align with the labeled selects */}
          <span className="brand-caption text-transparent block mb-1">
            Swap
          </span>
          <Button
            variant="outline"
            onClick={swap}
            disabled={!a && !b}
            aria-label="Swap project A and project B"
            title="Swap A and B"
          >
            <ArrowRightLeft className="w-4 h-4" />
          </Button>
        </div>
        <div className="flex-1">
          <label className="brand-caption text-muted-foreground block mb-1">
            Project B
          </label>
          <Select
            value={b || undefined}
            onValueChange={(v) => setSide("b", v)}
          >
            <SelectTrigger aria-label="Project B">
              <SelectValue placeholder="Pick project B…" />
            </SelectTrigger>
            <SelectContent>
              {pickerOptions.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {!a || !b ? (
        <div className="py-12 text-center text-muted-foreground">
          <p>
            Pick two projects to see shared actors, techniques, and IOCs.
          </p>
        </div>
      ) : loading ? (
        <p className="text-muted-foreground">Loading comparison…</p>
      ) : result ? (
        <div className="space-y-8">
          <CompareTable<string>
            heading="Shared actors"
            rows={result.shared_actors}
            emptyCopy="No shared actors between these projects."
            capReached={result.shared_actors.length === CAP}
            renderRow={(actorName, i) => (
              <tr key={i} className="border-b border-border/40">
                <td className="py-2 px-3 text-foreground">
                  <a
                    href={`/events?stix_type=threat-actor&actor=${encodeURIComponent(actorName)}`}
                    className="hover:underline inline-flex items-center gap-1"
                  >
                    {actorName}
                    <ExternalLink className="w-3 h-3" aria-hidden="true" />
                  </a>
                </td>
              </tr>
            )}
          />
          <CompareTable<string>
            heading="Shared techniques"
            rows={result.shared_techniques}
            emptyCopy="No shared techniques between these projects."
            capReached={result.shared_techniques.length === CAP}
            renderRow={(techniqueId, i) => (
              <tr key={i} className="border-b border-border/40">
                <td className="py-2 px-3 brand-mono text-foreground">
                  <a
                    href={`https://attack.mitre.org/techniques/${techniqueId.replace(".", "/")}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline inline-flex items-center gap-1"
                  >
                    {techniqueId}
                    <ExternalLink className="w-3 h-3" aria-hidden="true" />
                  </a>
                </td>
              </tr>
            )}
          />
          <CompareTable<SharedIOC>
            heading="Shared IOCs"
            rows={result.shared_iocs}
            emptyCopy="No shared IOCs between these projects."
            capReached={result.shared_iocs.length === CAP}
            renderRow={(ioc, i) => (
              <tr key={i} className="border-b border-border/40">
                <td className="py-2 px-3 brand-caption text-muted-foreground w-20">
                  {ioc.kind}
                </td>
                <td className="py-2 px-3 brand-mono text-foreground break-all">
                  {ioc.value}
                </td>
                <td className="py-2 px-3 w-20 text-right">
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => copyToClipboard(ioc.value)}
                    aria-label={`Copy ${ioc.kind} value ${ioc.value}`}
                    title="Copy to clipboard"
                  >
                    <Copy className="w-4 h-4" aria-hidden="true" />
                  </Button>
                </td>
              </tr>
            )}
          />
        </div>
      ) : null}
    </div>
  );
}
