/**
 * Test-only re-export of TABS from ProjectTabs.
 *
 * The ProjectTabs component is a "use client" module and cannot directly export
 * const values for use in non-component test assertions without importing the
 * full React component. This shim exports the TABS array as a plain TypeScript
 * export so test files can assert on tab order without needing to render.
 *
 * Phase 17 plan 17-08.
 */

export type TabDef = {
  key: string;
  label: string;
  route?: string;
};

export const TABS: TabDef[] = [
  { key: "overview", label: "Overview" },
  { key: "scope-keyword", label: "Keyword" },
  { key: "scope-service", label: "Service" },
  { key: "scope-domain", label: "Domain" },
  { key: "scope-certificate", label: "Certificate" },
  { key: "scope-whois", label: "WHOIS" },
  { key: "scope-as_number", label: "AS number" },
  { key: "scope-ip_range", label: "IP range" },
  { key: "sources", label: "Sources" },
  { key: "memberships", label: "Memberships" },
  { key: "settings", label: "Settings" },
  { key: "intel", label: "Intel", route: "intel" },
  { key: "graph", label: "Graph", route: "graph" },
  { key: "easm", label: "EASM", route: "easm" },
  { key: "assets", label: "Assets", route: "assets" },
  { key: "brand", label: "Brand", route: "brand" },
  { key: "scoring", label: "Scoring", route: "scoring" },
  { key: "ai-review", label: "AI Review", route: "ai-review" },
  { key: "digest", label: "Digest", route: "digest" },
];
