"use client";

/**
 * ProjectTable - /projects list table.
 *
 * Columns (UI-SPEC §Interaction Contracts /projects list):
 *   - Name          (with "Created by you" caption badge + ArchivedBadge)
 *   - Engagement    (EngagementTypeBadge)
 *   - Members       (member_count)
 *   - Created by    (Authentik sub truncated to 8 chars + ellipsis, mono)
 *   - Created at    (YYYY-MM-DD, date-only)
 *   - Actions       (Edit + Archive/Restore icons - HIDDEN on legacy row)
 *
 * Legacy sentinel rendering:
 *   - Detect via `project.id === LEGACY_PROJECT_ID`
 *   - Rendered at the bottom (not middle) so archived-toggle semantics stay
 *     predictable for operators
 *   - Muted row background, "Legacy data" badge on Name column
 *   - Tooltip (title attr) explains why it exists
 *   - Row is non-clickable (no onClick navigation)
 *   - Actions cell renders em-dash - no edit/archive affordances
 *
 * Empty state copy locked by UI-SPEC §Copywriting Contract.
 */

import { Archive, Edit, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import type { ProjectResponse } from "../lib/api";
import { LEGACY_PROJECT_ID } from "../lib/constants";
import { EngagementTypeBadge } from "./EngagementTypeBadge";
import { ArchivedBadge, LegacyBadge } from "./ArchivedBadge";

type Props = {
  projects: ProjectResponse[];
  onRowClick: (p: ProjectResponse) => void;
  onEdit: (p: ProjectResponse) => void;
  onArchive: (p: ProjectResponse) => void;
  onRestore: (p: ProjectResponse) => void;
};

function formatCreatedAt(iso: string): string {
  // "2026-04-19T12:34:56Z" -> "2026-04-19". Locale-independent slice keeps the
  // value stable across SSR + client hydration.
  return iso.slice(0, 10);
}

function truncateSub(sub: string): string {
  // Authentik subs are opaque opaque identifiers; showing the first 8 chars is
  // enough to visually distinguish creators without exposing full PII-ish ids
  // inline. The "…" suffix is intentional (UI-SPEC locks "first 8 chars").
  if (sub.length <= 8) return sub;
  return `${sub.slice(0, 8)}…`;
}

export function ProjectTable({
  projects,
  onRowClick,
  onEdit,
  onArchive,
  onRestore,
}: Props) {
  // Empty state: locked copy per UI-SPEC §Copywriting.
  if (projects.length === 0) {
    return (
      <div className="py-16 text-center">
        <h2 className="brand-heading mb-4">No projects yet</h2>
        <p className="text-muted-foreground">
          Create a project to scope intel, bind sources, and separate
          engagements.
        </p>
      </div>
    );
  }

  const legacy = projects.find((p) => p.id === LEGACY_PROJECT_ID);
  const regular = projects.filter((p) => p.id !== LEGACY_PROJECT_ID);

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead className="w-[140px]">Engagement</TableHead>
          <TableHead className="w-[90px]">Members</TableHead>
          <TableHead className="w-[140px]">Created by</TableHead>
          <TableHead className="w-[120px]">Created</TableHead>
          <TableHead className="w-[120px] text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {regular.map((p) => (
          <TableRow
            key={p.id}
            onClick={() => onRowClick(p)}
            className={`cursor-pointer hover:bg-muted/20 ${p.archived ? "opacity-60" : ""}`}
          >
            <TableCell>
              <div className="flex items-center gap-2">
                <span className="font-medium text-foreground">{p.name}</span>
                {p.creator_is_current_user && (
                  <Badge
                    variant="outline"
                    className="brand-caption"
                    style={{
                      backgroundColor: "rgba(29,158,117,0.15)",
                      borderColor: "var(--brand-primary)",
                      color: "var(--brand-primary)",
                    }}
                  >
                    Created by you
                  </Badge>
                )}
                {p.archived && <ArchivedBadge />}
              </div>
            </TableCell>
            <TableCell>
              <EngagementTypeBadge type={p.engagement_type} />
            </TableCell>
            <TableCell className="text-foreground">{p.member_count}</TableCell>
            <TableCell className="brand-mono text-muted-foreground">
              {truncateSub(p.created_by)}
            </TableCell>
            <TableCell className="text-foreground tabular-nums">
              {formatCreatedAt(p.created_at)}
            </TableCell>
            <TableCell className="text-right">
              {/* Stop row-click from firing when action buttons are used. */}
              <div
                className="inline-flex justify-end gap-1"
                onClick={(e) => e.stopPropagation()}
              >
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={`Edit project ${p.name}`}
                  onClick={() => onEdit(p)}
                >
                  <Edit className="w-4 h-4" />
                </Button>
                {p.archived ? (
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`Restore project ${p.name}`}
                    onClick={() => onRestore(p)}
                  >
                    <RotateCcw className="w-4 h-4" />
                  </Button>
                ) : (
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`Archive project ${p.name}`}
                    onClick={() => onArchive(p)}
                  >
                    <Archive className="w-4 h-4" />
                  </Button>
                )}
              </div>
            </TableCell>
          </TableRow>
        ))}

        {/* Legacy sentinel row - rendered last, non-clickable, no actions. */}
        {legacy && (
          <TableRow
            key={legacy.id}
            title="Pre-project-scoping events (v1.5) retained under this sentinel project for audit."
            className="bg-muted/10 opacity-75 border-t-2 border-border/60"
          >
            <TableCell>
              <div className="flex items-center gap-2">
                <span className="brand-mono text-foreground">{legacy.name}</span>
                <LegacyBadge />
              </div>
            </TableCell>
            <TableCell>
              <EngagementTypeBadge type={legacy.engagement_type} />
            </TableCell>
            <TableCell className="text-muted-foreground">
              {legacy.member_count}
            </TableCell>
            <TableCell className="brand-mono text-muted-foreground">
              system
            </TableCell>
            <TableCell className="text-muted-foreground tabular-nums">
              {formatCreatedAt(legacy.created_at)}
            </TableCell>
            <TableCell className="text-right text-muted-foreground">-</TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}
