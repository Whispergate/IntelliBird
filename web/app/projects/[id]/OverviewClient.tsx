"use client";

/**
 * OverviewClient - Overview tab content for /projects/[id] (
 * extended by Plan 11).
 *
 * Plan 10-09 shipped the skeleton: project name heading + EngagementTypeBadge
 * + ArchivedBadge + description card + summary dl.
 *
 * Plan 10-11 extensions (this revision):
 *   - Export button in the page-level header (opens ExportDialog); UI-SPEC
 *     §Export flow PRJ-07 "Entry: Export button in /projects/[id] page-level
 *     header (not per-tab)" - Overview is the page header.
 *   - Membership count and bound-source count surfaced in the Project summary
 *     dl so operators can see at a glance whether bindings are restricted.
 *     Fetched on mount alongside the Overview render; failures degrade
 *     silently to "-" so a transient backend hiccup doesn't block the page.
 *
 * Deferred to a later release (v2.1 per CONTEXT.md §deferred):
 *   - Event-count sparkline
 *   - Top tags widget
 *   - Source breakdown widget
 *   - Full widget grid equivalent to /red and /blue dashboards
 *
 * Scope discipline for Plan 11:
 *   - DO NOT touch ScopeTabContent / SettingsTabContent / EASMGatePreview
 *     (10-10 territory)
 *   - DO NOT touch /intel or /graph routes (10-12 territory)
 *   - DO NOT modify layout.tsx / page.tsx / ProjectBreadcrumb / ProjectTabs
 *     (10-09 + 10-10 territory)
 */

import { useEffect, useState } from "react";
import { Download } from "lucide-react";

import type { ProjectResponse } from "../lib/api";
import { listMemberships, listProjectSources } from "../lib/api";
import { EngagementTypeBadge } from "../components/EngagementTypeBadge";
import { ArchivedBadge } from "../components/ArchivedBadge";
import { Button } from "@/components/ui/button";
import { ExportDialog } from "./components/ExportDialog";
import { useProjectRole } from "./ProjectRoleProvider";
import InfluenceOpsWidget from "./InfluenceOpsWidget";

export function OverviewClient({ project }: { project: ProjectResponse }) {
  const { isObserver } = useProjectRole();
  const [exportOpen, setExportOpen] = useState(false);
  const [membershipCount, setMembershipCount] = useState<number | null>(
    project.member_count ?? null,
  );
  const [sourceCount, setSourceCount] = useState<number | null>(null);
  const [socialSourceCount, setSocialSourceCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [members, sources] = await Promise.all([
          listMemberships(project.id).catch(() => null),
          listProjectSources(project.id).catch(() => null),
        ]);
        if (cancelled) return;
        if (members) setMembershipCount(members.length);
        if (sources) {
          setSourceCount(sources.length);
          setSocialSourceCount(
            sources.filter((s) => s.feed_type === "social_listening").length
          );
        }
      } catch {
        // Silent degrade to "-" - overview is a summary view, not a
        // load-bearing surface. Transient backend errors should not block
        // rendering the project name + description.
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [project.id]);

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="brand-display text-foreground truncate">
            {project.name}
          </h1>
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <EngagementTypeBadge type={project.engagement_type} />
            {project.archived && <ArchivedBadge />}
          </div>
        </div>
        {!isObserver && (
          <Button
            onClick={() => setExportOpen(true)}
            style={{
              backgroundColor: "var(--brand-signal)",
              color: "var(--brand-ink)",
            }}
          >
            <Download className="w-4 h-4 mr-2" /> Export
          </Button>
        )}
      </header>

      <section className="rounded-md border border-border bg-card p-4">
        <h2 className="brand-heading mb-2 text-foreground">Description</h2>
        {project.description ? (
          <p className="text-foreground whitespace-pre-wrap">
            {project.description}
          </p>
        ) : (
          <p className="text-muted-foreground italic">No description yet.</p>
        )}
      </section>

      <section className="rounded-md border border-border bg-card p-4">
        <h2 className="brand-heading mb-4 text-foreground">Project summary</h2>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Members</dt>
          <dd className="text-foreground">
            {membershipCount ?? "-"}
          </dd>

          <dt className="text-muted-foreground">Bound sources</dt>
          <dd className="text-foreground">
            {sourceCount === null
              ? "-"
              : sourceCount === 0
                ? "0 (all sources visible)"
                : sourceCount}
          </dd>

          <dt className="text-muted-foreground">Created by</dt>
          <dd className="text-foreground brand-mono break-all">
            {project.created_by}
          </dd>

          <dt className="text-muted-foreground">Created at</dt>
          <dd className="text-foreground">
            {project.created_at.slice(0, 10)}
          </dd>

          <dt className="text-muted-foreground">Updated at</dt>
          <dd className="text-foreground">
            {project.updated_at.slice(0, 10)}
          </dd>
        </dl>
      </section>

      <InfluenceOpsWidget
        projectId={project.id}
        socialSourceCount={socialSourceCount}
      />

      <p className="text-sm text-muted-foreground">
        Full widget grid (event-count sparkline, top tags, source breakdown)
        lands in a later release.
      </p>

      <ExportDialog
        project={project}
        open={exportOpen}
        onClose={() => setExportOpen(false)}
      />
    </div>
  );
}
