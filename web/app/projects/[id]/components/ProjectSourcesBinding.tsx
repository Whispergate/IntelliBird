"use client";

/**
 * ProjectSourcesBinding — multi-select source checkbox list for /projects/[id]
 * Sources tab (PRJ-05).
 *
 * UI-SPEC §/projects/[id] detail §Sources tab locks:
 *   - List all globally configured sources (from /api/sources via fetchSources)
 *   - Pre-select sources currently bound to this project (listProjectSources)
 *   - Save button runs replaceProjectSources(projectId, checkedIds)
 *   - Empty state: "No sources bound — all sources are visible by default.
 *     Bind sources for air-gapped engagements."
 *
 * Semantics reminder (CONTEXT.md §decisions §project_sources binding):
 *   - A project with NO bindings sees all sources (open default — matches
 *     intel-team use cases where scope is the discrimininator, not sources).
 *   - A project with ≥1 binding sees ONLY the bound sources (TIBER / air-gap).
 *
 * Change-detection: a `dirty` derived boolean compares current checkbox state
 * against the last-saved set; Save is disabled when clean. Prevents a no-op
 * PUT round-trip and visually confirms "nothing to save" after a successful
 * save.
 */

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import type { ProjectResponse } from "../../lib/api";
import { listProjectSources, replaceProjectSources } from "../../lib/api";
import { fetchSources, type Source } from "@/app/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

function setsEqual(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const id of a) if (!b.has(id)) return false;
  return true;
}

export function ProjectSourcesBinding({
  project,
}: {
  project: ProjectResponse;
}) {
  const [allSources, setAllSources] = useState<Source[]>([]);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [savedRef, setSavedRef] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [all, proj] = await Promise.all([
          fetchSources(),
          listProjectSources(project.id),
        ]);
        if (cancelled) return;
        setAllSources(all);
        const boundIds = new Set(proj.map((p) => p.source_id));
        setChecked(new Set(boundIds));
        setSavedRef(new Set(boundIds));
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : "error";
        toast.error(`Could not load sources. ${msg}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [project.id]);

  const dirty = useMemo(
    () => !setsEqual(checked, savedRef),
    [checked, savedRef],
  );

  function toggle(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    try {
      await replaceProjectSources(project.id, Array.from(checked));
      setSavedRef(new Set(checked));
      toast.success(
        checked.size === 0
          ? "Source binding cleared — all sources visible."
          : `Bound ${checked.size} source${checked.size === 1 ? "" : "s"} to ${project.name}.`,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "error";
      if (msg.includes("unknown_source_id")) {
        toast.error(
          "One of the selected sources no longer exists. Reload and retry.",
        );
      } else if (msg.includes("legacy_project_immutable")) {
        toast.error("The legacy project is read-only and cannot be modified.");
      } else {
        toast.error(`Could not save binding. ${msg}`);
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="text-muted-foreground">Loading sources…</div>;
  }

  const boundCount = checked.size;
  const totalCount = allSources.length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="brand-heading text-foreground">Bind sources</h2>
          <p className="text-sm text-muted-foreground max-w-2xl">
            When no sources are bound, all global sources feed this project&apos;s
            intel view. Binding a subset restricts the project to those
            sources only — useful for air-gapped engagements (e.g. TIBER) where
            operators must control which feeds are visible.
          </p>
        </div>
        <Button
          onClick={save}
          disabled={saving || !dirty}
          style={{
            backgroundColor: "var(--brand-signal)",
            color: "var(--brand-ink)",
          }}
        >
          {saving ? "Saving…" : dirty ? "Save binding" : "Saved"}
        </Button>
      </div>

      {totalCount === 0 ? (
        <div className="py-12 text-center text-muted-foreground">
          <h3 className="brand-heading mb-2 text-foreground">
            No sources configured
          </h3>
          <p>
            Add sources under{" "}
            <a
              href="/sources"
              className="underline underline-offset-2 hover:text-foreground"
            >
              /sources
            </a>
            {" "}before binding them to a project.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {allSources.map((s) => {
            const id = `bind-${s.id}`;
            const isChecked = checked.has(s.id);
            return (
              <li
                key={s.id}
                className="flex items-center gap-3 p-3 rounded-md border border-border bg-card hover:bg-accent/5 transition-colors"
              >
                <Checkbox
                  id={id}
                  checked={isChecked}
                  onCheckedChange={() => toggle(s.id)}
                  aria-label={`Bind source ${s.name}`}
                />
                <label
                  htmlFor={id}
                  className="flex-1 flex items-center gap-2 cursor-pointer min-w-0"
                >
                  <span className="text-foreground truncate">{s.name}</span>
                  <Badge variant="outline" className="brand-caption shrink-0">
                    {s.feed_type}
                  </Badge>
                </label>
              </li>
            );
          })}
        </ul>
      )}

      <p className="text-sm text-muted-foreground">
        {totalCount === 0
          ? null
          : boundCount === 0
            ? "No sources bound — all sources are visible by default."
            : `${boundCount} of ${totalCount} source${totalCount === 1 ? "" : "s"} bound to this project.`}
      </p>
    </div>
  );
}
