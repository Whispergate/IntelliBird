"use client";

/**
 * DigestView — Daily Digest page client component (Phase 17 plan 17-09 / AI-07).
 * Surface 3 per 17-UI-SPEC.md.
 *
 * - Fetches latest ai_summaries digest row from GET /api/projects/{id}/ai/digest.
 * - Lightweight markdown-lite pass: ## headings → <h3>, - bullets → <li>, footer → <p>.
 * - Empty state: FileText icon + copy per UI-SPEC §Surface 3 empty state.
 * - "Generate now" button: Admin only, POST /api/projects/{id}/digest/generate,
 *   disabled for 10s to prevent rapid-fire, toast.success("Digest generation queued.").
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { FileText } from "lucide-react";
import { useSession } from "next-auth/react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// Types matching backend schemas/ai.py AIDigestResponse
// ---------------------------------------------------------------------------

interface DigestData {
  id: string;
  project_id: string;
  summary_type: string;
  provider_used: string;
  model_used: string;
  prompt_template_version: string;
  summary_text: string;
  tokens_used: number;
  requires_analyst_review: boolean;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(iso: string | null): string {
  if (!iso) return "Not yet generated";
  const diffMs = Date.now() - Date.parse(iso);
  if (diffMs < 0) return "just now";
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

/**
 * Lightweight markdown-lite renderer for structured digest text.
 *
 * Lines starting with "## " → <h3> (brand-heading)
 * Lines starting with "- "  → <li> (inside <ul>)
 * Lines matching footer pattern → <p> with muted styling
 * Other lines → <p>
 *
 * Consecutive <li> elements are wrapped in a single <ul>. This requires a
 * two-pass approach: collect lines then group runs of bullets.
 */
function renderDigestLines(text: string): React.ReactNode[] {
  const lines = text.split("\n");
  const result: React.ReactNode[] = [];
  let bulletBuffer: Array<{ line: string; idx: number }> = [];

  function flushBullets() {
    if (bulletBuffer.length === 0) return;
    const items = bulletBuffer.map(({ line, idx }) => (
      <li key={idx} className="ml-4 text-sm">
        {line.slice(2)}
      </li>
    ));
    result.push(
      <ul key={`ul-${bulletBuffer[0].idx}`} className="list-disc space-y-0.5 mb-2">
        {items}
      </ul>,
    );
    bulletBuffer = [];
  }

  lines.forEach((line, idx) => {
    if (line.startsWith("## ")) {
      flushBullets();
      result.push(
        <h3 key={idx} className="brand-heading mt-6 mb-2">
          {line.slice(3)}
        </h3>,
      );
    } else if (line.startsWith("- ")) {
      bulletBuffer.push({ line, idx });
    } else if (line.match(/^— Summary based on \d+ of \d+ events$/)) {
      flushBullets();
      result.push(
        <p key={idx} className="text-muted-foreground text-xs mt-4 border-t border-border pt-2">
          {line}
        </p>,
      );
    } else if (line.trim() === "") {
      flushBullets();
      // skip blank lines
    } else {
      flushBullets();
      result.push(
        <p key={idx} className="mb-2 text-sm">
          {line}
        </p>,
      );
    }
  });
  flushBullets();
  return result;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DigestView({ projectId }: { projectId: string }) {
  const { data: session } = useSession();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const role = (session?.user as any)?.role as string | undefined;
  const isAdmin = !session || role === "Admin"; // dev-mode: no session → treat as admin

  const [digest, setDigest] = useState<DigestData | null | "empty">(null);
  const [generateDisabled, setGenerateDisabled] = useState(false);

  // Fetch latest digest on mount
  useEffect(() => {
    async function loadDigest() {
      try {
        const res = await fetch(`/api/projects/${projectId}/ai/digest`, {
          credentials: "include",
        });
        if (res.status === 404) {
          setDigest("empty");
          return;
        }
        if (!res.ok) {
          toast.error("Could not load digest. Check your connection and refresh.");
          setDigest("empty");
          return;
        }
        const data: DigestData = await res.json();
        setDigest(data);
      } catch {
        toast.error("Could not load digest. Check your connection and refresh.");
        setDigest("empty");
      }
    }
    loadDigest();
  }, [projectId]);

  async function handleGenerateNow() {
    setGenerateDisabled(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/digest/generate`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        toast.error(`Could not trigger digest. ${text || "Unknown error."}`);
      } else {
        toast.success("Digest generation queued.");
      }
    } catch {
      toast.error("Could not trigger digest. Check your connection.");
    }
    // Re-enable after 10s
    setTimeout(() => setGenerateDisabled(false), 10_000);
  }

  const lastGeneratedAt =
    digest && digest !== "empty" ? digest.created_at : null;

  return (
    <div className="max-w-3xl mx-auto pt-6">
      {/* Page header */}
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="brand-heading text-foreground">Daily Digest</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {lastGeneratedAt
              ? `Last generated ${relativeTime(lastGeneratedAt)}`
              : "Not yet generated"}
          </p>
        </div>
        {isAdmin && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleGenerateNow}
            disabled={generateDisabled}
          >
            Generate now
          </Button>
        )}
      </div>

      {/* Digest body */}
      {digest === null ? (
        // Loading skeleton
        <Card>
          <CardContent className="pt-6">
            <p className="text-muted-foreground text-sm">Loading…</p>
          </CardContent>
        </Card>
      ) : digest === "empty" ? (
        // Empty state
        <Card>
          <CardContent className="pt-6 flex flex-col items-center py-12">
            <FileText size={32} className="text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-muted-foreground text-sm text-center">
              No digest generated yet
            </p>
            <p className="text-xs text-muted-foreground text-center mt-1">
              Digests run automatically at 06:00 UTC when AI digest is enabled.
              Admins can generate one manually above.
            </p>
          </CardContent>
        </Card>
      ) : (
        // Digest content
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm leading-relaxed text-foreground whitespace-pre-line">
              {renderDigestLines(digest.summary_text)}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
