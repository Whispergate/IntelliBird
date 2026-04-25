"use client";

/**
 * ProjectTabs — 17-tab sub-navigation strip for /projects/[id]/*.
 *
 * Locked order (per 10-UI-SPEC §/projects/[id] detail §Tabs + 11-UI-SPEC §Surface 1):
 *   1. Overview
 *   2. Keyword scope          (?tab=scope-keyword)
 *   3. Service scope          (?tab=scope-service)
 *   4. Domain scope           (?tab=scope-domain)
 *   5. Certificate scope      (?tab=scope-certificate)
 *   6. WHOIS scope            (?tab=scope-whois)
 *   7. AS number scope        (?tab=scope-as_number)
 *   8. IP range scope         (?tab=scope-ip_range)
 *   9. Sources                (?tab=sources)
 *  10. Memberships            (?tab=memberships)
 *  11. Settings               (?tab=settings)
 *  12. Intel                  → navigates to /projects/[id]/intel (nested route)
 *  13. Graph                  → navigates to /projects/[id]/graph (nested route)
 *  14. EASM                   → navigates to /projects/[id]/easm (nested route)
 *  15. Assets                 → navigates to /projects/[id]/assets (nested route)
 *  16. Brand                  → navigates to /projects/[id]/brand (nested route)
 *  17. Scoring                → navigates to /projects/[id]/scoring (nested route)
 *
 * Navigation rules:
 *   - Tabs 1..11 use ?tab= query param (router.replace so history doesn't
 *     pile up on every click).
 *   - Tabs 12..16 navigate to nested routes (router.push).
 *
 * Horizontal scroll + fade-edge (per 10-UI-SPEC §Tab scroll):
 *   - Container: overflow-x-auto with `scrollbarWidth: "none"` inline
 *     (Tailwind has no first-party hide-scrollbar utility at v4 without a
 *     plugin; the inline style covers Firefox; `::-webkit-scrollbar` is
 *     suppressed via the `scrollbar-none` ad-hoc class name used below with
 *     an inline `WebkitScrollbar` via a CSS rule injected in globals.css if
 *     needed — for M2 we rely on `style` + the fade overlays to communicate
 *     overflow; the scrollbar itself remains acceptable if visible).
 *   - Fade indicators: two absolute-positioned gradient strips driven by an
 *     onScroll + ResizeObserver state machine. scrollLeft > 4 → show left
 *     fade; scrollLeft < scrollWidth - clientWidth - 4 → show right fade.
 *     Chose onScroll + resize (NOT IntersectionObserver): STATE.md Phase 5
 *     precedent (DashboardShell onScroll in plan 05-02). IntersectionObserver
 *     would need sentinel elements at both ends and fires only on threshold
 *     crossings, not on every pixel of scroll — less precise for fade
 *     animation.
 *
 * Active tab detection:
 *   - pathname ends with /intel → "intel" active (no ?tab= read)
 *   - pathname ends with /graph → "graph" active
 *   - pathname includes /easm → "easm" active (matches all /projects/[id]/easm* paths)
 *   - pathname includes /assets → "assets" active (matches all /projects/[id]/assets* paths per 12.1-UI-SPEC §Surface 1)
 *   - pathname includes /brand → "brand" active (matches /brand and /brand/terms per 12-UI-SPEC §Surface 1)
 *   - else: sp.get("tab") ?? "overview"
 *
 * Next.js 15 note: useSearchParams requires a Suspense boundary up the tree.
 * The parent ProjectLayout is a server component, so Next.js wraps this
 * client subtree automatically. No local Suspense needed.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

type TabDef = {
  key: string;
  label: string;
  /** If set, clicking this tab navigates to /projects/<id>/<route>. */
  route?: string;
};

const TABS: TabDef[] = [
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
];

export function ProjectTabs({
  projectId,
}: {
  projectId: string;
  /** Kept for future use (aria-label, screen-reader context). */
  projectName: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [showLeftFade, setShowLeftFade] = useState(false);
  const [showRightFade, setShowRightFade] = useState(false);

  const activeKey = (() => {
    if (pathname.endsWith("/intel")) return "intel";
    if (pathname.endsWith("/graph")) return "graph";
    if (pathname.includes("/easm")) return "easm";
    if (pathname.includes("/assets")) return "assets";
    if (pathname.includes("/brand")) return "brand";
    if (pathname.includes("/scoring")) return "scoring";
    return sp.get("tab") ?? "overview";
  })();

  // Fade-edge overflow indicators.
  // Pattern: onScroll + window resize listener (STATE.md Phase 5 Plan 02
  // precedent). Threshold of 4px absorbs sub-pixel scroll jitter on trackpads.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const update = () => {
      const atLeftEdge = el.scrollLeft <= 4;
      const atRightEdge = el.scrollLeft >= el.scrollWidth - el.clientWidth - 4;
      setShowLeftFade(!atLeftEdge);
      setShowRightFade(!atRightEdge);
    };

    update();
    el.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);

    // ResizeObserver catches container resizes that don't fire window resize
    // (e.g. sidebar toggle changing layout width). Fallback gracefully if the
    // browser lacks it (very old envs; Next.js 15 baseline is evergreen).
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(update);
      ro.observe(el);
    }

    return () => {
      el.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      ro?.disconnect();
    };
  }, []);

  function onTabChange(key: string) {
    const tab = TABS.find((t) => t.key === key);
    if (!tab) return;
    if (tab.route) {
      // Nested route (Intel / Graph). Use push so back-button returns to the
      // previous tab rather than just bouncing query params.
      router.push(`/projects/${projectId}/${tab.route}`);
    } else {
      // Same-page tab: replace (not push) so rapid tab-switching doesn't
      // pollute history.
      const param = key === "overview" ? "" : `?tab=${key}`;
      router.replace(`/projects/${projectId}${param}`);
    }
  }

  return (
    <div className="relative border-b border-border">
      {/* Left fade — signals more tabs scrollable to the left */}
      {showLeftFade && (
        <div
          aria-hidden="true"
          className="absolute left-0 top-0 bottom-0 w-8 pointer-events-none z-10"
          style={{
            background:
              "linear-gradient(to right, var(--brand-ink), transparent)",
          }}
        />
      )}
      {/* Right fade — signals more tabs scrollable to the right */}
      {showRightFade && (
        <div
          aria-hidden="true"
          className="absolute right-0 top-0 bottom-0 w-8 pointer-events-none z-10"
          style={{
            background:
              "linear-gradient(to left, var(--brand-ink), transparent)",
          }}
        />
      )}
      <div
        ref={scrollRef}
        className="overflow-x-auto"
        style={{
          // Hide native scrollbar on Firefox; WebKit relies on the fade to
          // communicate overflow (scrollbar may still show — acceptable for M2).
          scrollbarWidth: "none",
        }}
      >
        <Tabs value={activeKey} onValueChange={onTabChange}>
          <TabsList className="inline-flex gap-1 h-auto bg-transparent p-0 rounded-none">
            {TABS.map((t) => (
              <TabsTrigger
                key={t.key}
                value={t.key}
                className={[
                  // Reset shadcn defaults that conflict with a horizontal strip
                  "px-4 py-2 whitespace-nowrap text-sm rounded-none shadow-none",
                  "border-b-2 border-transparent",
                  // Active: underline + full foreground colour
                  "data-[state=active]:border-[var(--brand-signal)]",
                  "data-[state=active]:text-foreground",
                  "data-[state=active]:bg-transparent",
                  "data-[state=active]:shadow-none",
                  // Inactive: muted, hover lifts to foreground
                  "text-muted-foreground hover:text-foreground",
                  "transition-colors",
                ].join(" ")}
              >
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>
    </div>
  );
}
