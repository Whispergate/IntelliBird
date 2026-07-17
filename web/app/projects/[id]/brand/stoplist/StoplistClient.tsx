"use client";

/**
 * StoplistClient — (BRAND-01 frontend).
 *
 * UI-SPEC §Surface 1 — Stoplist Tab.
 *
 * Role gating via useProjectRole:
 *   - Lead+ (isLead): sees Add form (Input + Button) + per-row Delete button
 *   - Observer/Contributor: read-only table
 *
 * Client-side fetch uses browser relative URL (→ /api/[...path] proxy injects
 * bearer). Server-side initial data is passed as props from the RSC page.tsx.
 */

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { useProjectRole } from "@/app/projects/[id]/ProjectRoleProvider";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BrandStoplistTerm {
  id: string;
  term: string;
  created_at: string;
  created_by_user_id: string | null;
}

// ---------------------------------------------------------------------------
// Format helpers — mirrors TermsClient.tsx
// ---------------------------------------------------------------------------

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    const months = [
      "Jan","Feb","Mar","Apr","May","Jun",
      "Jul","Aug","Sep","Oct","Nov","Dec",
    ];
    const day = String(d.getUTCDate()).padStart(2, "0");
    return `${day} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  } catch {
    return iso.slice(0, 10);
  }
}

function truncateEmail(email: string | null | undefined): string {
  if (!email) return "—";
  return email.length > 20 ? `${email.slice(0, 20)}…` : email;
}

// ---------------------------------------------------------------------------
// Error response helper
// ---------------------------------------------------------------------------

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (data && typeof data === "object" && "detail" in data) {
      return String((data as { detail?: unknown }).detail ?? `${res.status} ${res.statusText}`);
    }
  } catch {
    // ignore
  }
  return `${res.status} ${res.statusText}`;
}

// ---------------------------------------------------------------------------
// StoplistClient
// ---------------------------------------------------------------------------

interface StoplistClientProps {
  projectId: string;
  initialTerms: BrandStoplistTerm[];
}

export function StoplistClient({
  projectId,
  initialTerms,
}: StoplistClientProps) {
  const { isLead, isObserver } = useProjectRole();

  const [terms, setTerms] = useState<BrandStoplistTerm[]>(initialTerms);
  const [newTerm, setNewTerm] = useState("");
  const [busy, setBusy] = useState(false);

  // ---- Add term -----------------------------------------------------------

  async function handleAdd() {
    const trimmed = newTerm.trim();
    if (!trimmed || busy) return;

    if (trimmed.length < 1 || trimmed.length > 200) {
      toast.error("Term must be between 1 and 200 characters.");
      return;
    }

    setBusy(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/brand/stoplist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ term: trimmed }),
      });

      if (!res.ok) {
        const detail = await parseErrorDetail(res);
        if (res.status === 409) {
          toast.error("Term already in stoplist for this project.");
        } else {
          toast.error(`Could not add term. ${detail}`);
        }
        return;
      }

      const created: BrandStoplistTerm = await res.json();
      setTerms((prev) => [created, ...prev]);
      setNewTerm("");
      toast.success("Term added to stoplist.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      toast.error(`Could not add term. ${msg}`);
    } finally {
      setBusy(false);
    }
  }

  // ---- Delete term --------------------------------------------------------

  async function handleDelete(termId: string) {
    try {
      const res = await fetch(
        `/api/projects/${projectId}/brand/stoplist/${termId}`,
        { method: "DELETE" },
      );

      if (!res.ok) {
        const detail = await parseErrorDetail(res);
        toast.error(`Could not remove term. ${detail}`);
        return;
      }

      setTerms((prev) => prev.filter((t) => t.id !== termId));
      toast.success("Term removed from stoplist.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      toast.error(`Could not remove term. ${msg}`);
    }
  }

  // ---- Render -------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href={`/projects/${projectId}/brand`}
        className="inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3 w-3" />
        Brand dashboard
      </Link>

      {/* Header — UI-SPEC §1a */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="font-medium leading-tight" style={{ fontSize: "32px" }}>
          Brand Stoplist
        </h1>
        {isLead && (
          <div className="flex items-center gap-2">
            <Input
              type="text"
              placeholder="Add term to stoplist"
              value={newTerm}
              onChange={(e) => setNewTerm(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              className="w-56 h-9 text-sm"
              maxLength={200}
              aria-label="New stoplist term"
            />
            <Button
              size="sm"
              onClick={handleAdd}
              disabled={!newTerm.trim() || busy}
            >
              Add term
            </Button>
          </div>
        )}
      </div>

      {/* Content — UI-SPEC §1b */}
      {terms.length === 0 ? (
        /* Empty state — copy differs by role */
        <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <h2 className="text-[22px] font-medium leading-[1.3]">
            No stoplist terms yet.
          </h2>
          <p className="text-muted-foreground max-w-md leading-[1.7]">
            {isObserver
              ? "No terms have been added to the project stoplist."
              : "Add terms to suppress false-positive brand matches for this project. Global stoplist terms still apply."}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-border bg-card text-left">
                <th className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground">
                  Term
                </th>
                <th
                  className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
                  style={{ width: "200px", minWidth: "200px" }}
                >
                  Created by
                </th>
                <th
                  className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
                  style={{ width: "140px", minWidth: "140px" }}
                >
                  Created at
                </th>
                {isLead && (
                  <th
                    className="py-2 px-3 text-[12px] font-medium uppercase tracking-wide text-muted-foreground"
                    style={{ width: "60px", minWidth: "60px" }}
                  >
                    Actions
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {terms.map((term) => (
                <tr
                  key={term.id}
                  className="border-b border-border/40 last:border-b-0"
                  style={{ height: "44px" }}
                  data-testid={`stoplist-row-${term.id}`}
                >
                  {/* Term — monospace */}
                  <td className="py-2 px-3">
                    <span className="font-mono text-[12px] text-foreground">
                      {term.term}
                    </span>
                  </td>

                  {/* Created by — truncated 20ch with tooltip */}
                  <td className="py-2 px-3">
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="font-mono text-[12px] text-muted-foreground">
                            {truncateEmail(term.created_by_user_id)}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>
                          {term.created_by_user_id ?? "—"}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </td>

                  {/* Created at */}
                  <td className="py-2 px-3 text-sm text-muted-foreground">
                    {fmtDate(term.created_at)}
                  </td>

                  {/* Actions — Lead+ only */}
                  {isLead && (
                    <td className="py-2 px-3">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Delete term"
                        className="text-muted-foreground hover:text-destructive"
                        onClick={() => handleDelete(term.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
