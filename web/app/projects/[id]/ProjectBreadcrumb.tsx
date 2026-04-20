"use client";

/**
 * ProjectBreadcrumb — Projects / <project name> / <section> nav strip.
 *
 * Appears beneath the global TopNav (which stays rendered by root layout /
 * DashboardShell for /red and /blue routes) and above the 13-tab ProjectTabs
 * strip.
 *
 * Section derivation:
 *   - If pathname ends with /intel → "Intel" (nested route)
 *   - If pathname ends with /graph → "Graph" (nested route)
 *   - Else read ?tab=<key> and look up its label via TAB_LABELS
 *   - Default: "Overview"
 *
 * `<Link href="/projects">` is the only interactive element (returns to list).
 * Project name is plain text (non-interactive — clicking it would re-route to
 * itself, which is confusing). Section is plain text (tab switch is the way
 * to change it).
 *
 * Next.js 15 `useSearchParams` requires a Suspense boundary at the caller
 * level; the parent layout.tsx is a server component so Next.js wraps this
 * client subtree automatically. No explicit Suspense needed here.
 */

import Link from "next/link";
import { useSearchParams, usePathname } from "next/navigation";

const TAB_LABELS: Record<string, string> = {
  overview: "Overview",
  "scope-keyword": "Keyword scope",
  "scope-service": "Service scope",
  "scope-domain": "Domain scope",
  "scope-certificate": "Certificate scope",
  "scope-whois": "WHOIS scope",
  "scope-as_number": "AS number scope",
  "scope-ip_range": "IP range scope",
  sources: "Sources",
  memberships: "Memberships",
  settings: "Settings",
  intel: "Intel",
  graph: "Graph",
};

export function ProjectBreadcrumb({ projectName }: { projectName: string }) {
  const sp = useSearchParams();
  const pathname = usePathname();

  let section: string = "Overview";
  if (pathname.endsWith("/intel")) {
    section = "Intel";
  } else if (pathname.endsWith("/graph")) {
    section = "Graph";
  } else {
    const tabKey = sp.get("tab") ?? "overview";
    section = TAB_LABELS[tabKey] ?? "Overview";
  }

  return (
    <nav
      aria-label="Breadcrumb"
      className="text-sm text-muted-foreground mb-4"
    >
      <ol className="flex items-center gap-2">
        <li>
          <Link
            href="/projects"
            className="hover:text-foreground transition-colors"
          >
            Projects
          </Link>
        </li>
        <li aria-hidden="true" className="text-muted-foreground/60">
          /
        </li>
        <li>
          <span className="text-foreground">{projectName}</span>
        </li>
        <li aria-hidden="true" className="text-muted-foreground/60">
          /
        </li>
        <li aria-current="page">
          <span>{section}</span>
        </li>
      </ol>
    </nav>
  );
}
