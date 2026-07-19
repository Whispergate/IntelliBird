/**
 * MatchDetailDrawer.test.tsx - (BRAND-02 frontend).
 *
 * Coverage:
 *   - Provenance renders all 3 detector tiers (fts, ct_log, dnstwist) with correct badges
 *   - Aggregate counts row renders 4 badges with correct labels
 *   - Timeline renders entries with action colours; empty state copy
 *   - Observer: action footer hidden; Lead: footer + textarea visible
 *   - Note submission: PATCH called with {lifecycle_status, note}
 *   - Note maxLength=500 (capped)
 *   - Note counter shows {N}/500
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// jsdom pointer events polyfill (Radix requirement)
if (
  typeof Element !== "undefined" &&
  !Element.prototype.hasPointerCapture
) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}

// ---------------------------------------------------------------------------
// Mocks - hoisted before component imports
// ---------------------------------------------------------------------------

vi.mock("sonner", () => ({
  toast: {
    info: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/projects/proj-1/brand",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock ProjectRoleProvider so we can inject isObserver/isLead from outside
vi.mock(
  "@/app/projects/[id]/ProjectRoleProvider",
  async () => {
    const { createContext, useContext } = await import("react");

    type ProjectRoleContextValue = {
      role: string | null;
      isAdmin: boolean;
      isLead: boolean;
      isContributor: boolean;
      isObserver: boolean;
    };

    const ProjectRoleContext = createContext<ProjectRoleContextValue>({
      role: "Lead",
      isAdmin: false,
      isLead: true,
      isContributor: true,
      isObserver: false,
    });

    return {
      ProjectRoleProvider: ({
        value,
        children,
      }: {
        value: ProjectRoleContextValue;
        children: React.ReactNode;
      }) => (
        <ProjectRoleContext.Provider value={value}>
          {children}
        </ProjectRoleContext.Provider>
      ),
      useProjectRole: () => useContext(ProjectRoleContext),
    };
  },
);

import { ProjectRoleProvider } from "@/app/projects/[id]/ProjectRoleProvider";
import { MatchDetailDrawer } from "@/app/projects/[id]/brand/MatchDetailDrawer";
import type {
  MatchDetailsResponse,
  HistoryEntry,
} from "@/app/projects/[id]/brand/lib/api";
import type { BrandMatchRead } from "@/app/projects/[id]/brand/lib/api";

// ---------------------------------------------------------------------------
// Role context helpers
// ---------------------------------------------------------------------------

type RoleValues = {
  role: string | null;
  isAdmin: boolean;
  isLead: boolean;
  isContributor: boolean;
  isObserver: boolean;
};

const LEAD_ROLE: RoleValues = {
  role: "Lead",
  isAdmin: false,
  isLead: true,
  isContributor: true,
  isObserver: false,
};

const OBSERVER_ROLE: RoleValues = {
  role: "Observer",
  isAdmin: false,
  isLead: false,
  isContributor: false,
  isObserver: true,
};

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FTS_MATCH: BrandMatchRead = {
  id: "match-fts-001",
  project_id: "proj-1",
  term_id: "term-1",
  matched_value: "acmecorp-phishing.com",
  match_source: "fts",
  severity: "high",
  lifecycle_status: "new",
  dismiss_until: null,
  first_seen: "2026-04-01T10:00:00Z",
  last_seen: "2026-04-29T08:00:00Z",
};

const CT_LOG_MATCH: BrandMatchRead = {
  ...FTS_MATCH,
  id: "match-ctlog-001",
  match_source: "ct_log",
};

const DNSTWIST_MATCH: BrandMatchRead = {
  ...FTS_MATCH,
  id: "match-dns-001",
  match_source: "dnstwist",
};

const HISTORY_ENTRIES: HistoryEntry[] = [
  {
    acted_at: "2026-04-28T12:00:00Z",
    actor_id: "user-1",
    actor_email: "alice@example.com",
    action: "confirmed",
    prev_status: "new",
    new_status: "confirmed",
    note: "legit match",
    match_id: "match-fts-001",
    matched_value: "acmecorp-phishing.com",
  },
  {
    acted_at: "2026-04-27T09:00:00Z",
    actor_id: "user-2",
    actor_email: "bob@example.com",
    action: "dismissed",
    prev_status: "new",
    new_status: "dismissed",
    note: null,
    match_id: "match-fts-002",
    matched_value: "acme-legit.com",
  },
  {
    acted_at: "2026-04-26T14:00:00Z",
    actor_id: "user-1",
    actor_email: "alice@example.com",
    action: "watchlist",
    prev_status: "new",
    new_status: "watchlist",
    note: null,
    match_id: "match-fts-003",
    matched_value: "acmecorp-fake.net",
  },
];

const FTS_DETAILS: MatchDetailsResponse = {
  match_id: "match-fts-001",
  provenance: {
    detector: "fts",
    raw_input: "Event abc12345",
    matched_value: "acmecorp-phishing.com",
    similarity: null,
  },
  aggregate_counts: {
    new: 3,
    confirmed: 5,
    dismissed: 2,
    watchlist: 1,
  },
  timeline: HISTORY_ENTRIES,
};

const CT_LOG_DETAILS: MatchDetailsResponse = {
  ...FTS_DETAILS,
  match_id: "match-ctlog-001",
  provenance: {
    detector: "ct_log",
    raw_input: "Let's Encrypt / 2026-04-01",
    matched_value: "acmecorp-phishing.com",
    similarity: null,
  },
};

const DNSTWIST_DETAILS: MatchDetailsResponse = {
  ...FTS_DETAILS,
  match_id: "match-dns-001",
  provenance: {
    detector: "dnstwist",
    raw_input: "homoglyph",
    matched_value: "acmecorp-phishing.com",
    similarity: null,
  },
};

const EMPTY_TIMELINE_DETAILS: MatchDetailsResponse = {
  ...FTS_DETAILS,
  timeline: [],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderDrawer(
  match: BrandMatchRead,
  details: MatchDetailsResponse,
  role: RoleValues = LEAD_ROLE,
) {
  const onClose = vi.fn();
  const onUpdate = vi.fn();

  render(
    // @ts-expect-error test mock accepts value prop
    <ProjectRoleProvider value={role}>
      <MatchDetailDrawer
        projectId="proj-1"
        match={match}
        details={details}
        open={true}
        onClose={onClose}
        onUpdate={onUpdate}
      />
    </ProjectRoleProvider>,
  );

  return { onClose, onUpdate };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MatchDetailDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ---- Provenance rendering ------------------------------------------------

  it("test_renders_provenance_fts: FTS detector badge + raw_input + similarity -", () => {
    renderDrawer(FTS_MATCH, FTS_DETAILS);

    // Detector badge
    expect(screen.getByText("FTS")).toBeInTheDocument();

    // Raw input
    expect(screen.getByText("Event abc12345")).toBeInTheDocument();

    // Matched value - may appear multiple times (provenance + timeline links)
    expect(screen.getAllByText("acmecorp-phishing.com").length).toBeGreaterThan(0);

    // Similarity always "-"
    expect(screen.getByText("-")).toBeInTheDocument();
  });

  it("test_renders_provenance_ctlog: CT log badge renders with correct raw_input", () => {
    renderDrawer(CT_LOG_MATCH, CT_LOG_DETAILS);

    // CT log badge label
    expect(screen.getByText("CT log")).toBeInTheDocument();

    // Raw input from cert provenance
    expect(screen.getByText("Let's Encrypt / 2026-04-01")).toBeInTheDocument();
  });

  it("test_renders_provenance_dnstwist: dnstwist badge + fuzzer raw_input", () => {
    renderDrawer(DNSTWIST_MATCH, DNSTWIST_DETAILS);

    // dnstwist badge label
    expect(screen.getByText("dnstwist")).toBeInTheDocument();

    // Raw input from fuzzer name
    expect(screen.getByText("homoglyph")).toBeInTheDocument();
  });

  // ---- Aggregate counts ----------------------------------------------------

  it("test_renders_aggregate_counts: all 4 badges with correct counts", () => {
    renderDrawer(FTS_MATCH, FTS_DETAILS);

    expect(screen.getByText(/Confirmed 5x/)).toBeInTheDocument();
    expect(screen.getByText(/Dismissed 2x/)).toBeInTheDocument();
    expect(screen.getByText(/Watchlist 1x/)).toBeInTheDocument();
    expect(screen.getByText(/New 3x/)).toBeInTheDocument();
  });

  // ---- Timeline ------------------------------------------------------------

  it("test_renders_timeline: 3 entries render with actor emails and action labels", () => {
    renderDrawer(FTS_MATCH, FTS_DETAILS);

    // All actors (alice appears twice - two entries)
    expect(screen.getAllByText("alice@example.com").length).toBeGreaterThan(0);
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();

    // Action labels
    expect(screen.getByText("confirmed")).toBeInTheDocument();
    expect(screen.getByText("dismissed")).toBeInTheDocument();
    expect(screen.getByText("watchlisted")).toBeInTheDocument();

    // Note renders inline
    expect(screen.getByText("legit match")).toBeInTheDocument();
  });

  it("test_renders_empty_timeline: timeline=[] shows empty state copy", () => {
    renderDrawer(FTS_MATCH, EMPTY_TIMELINE_DETAILS);

    expect(
      screen.getByText("No prior actions recorded."),
    ).toBeInTheDocument();
  });

  // ---- Observer / Lead role gate -------------------------------------------

  it("test_observer_hides_footer: Observer sees no Confirm/Dismiss/Watchlist buttons and no Note textarea", () => {
    renderDrawer(FTS_MATCH, FTS_DETAILS, OBSERVER_ROLE);

    expect(
      screen.queryByRole("button", { name: /confirm/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /dismiss/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /watchlist/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/note/i),
    ).not.toBeInTheDocument();
  });

  it("test_lead_shows_footer: Lead sees Confirm/Dismiss/Watchlist buttons and Note textarea", () => {
    renderDrawer(FTS_MATCH, FTS_DETAILS, LEAD_ROLE);

    expect(
      screen.getByRole("button", { name: /confirm/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /dismiss/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /watchlist/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/note \(optional\)/i),
    ).toBeInTheDocument();
  });

  // ---- Action submission ---------------------------------------------------

  it("test_action_submit: click Confirm with note → fetch PATCH with {lifecycle_status, note}", async () => {
    const patchResponse: BrandMatchRead = {
      ...FTS_MATCH,
      lifecycle_status: "confirmed",
    };

    // Mock patchBrandMatch fetch (PATCH) + refetch details (GET)
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(patchResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(FTS_DETAILS), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    const user = userEvent.setup();
    const { onUpdate } = renderDrawer(FTS_MATCH, FTS_DETAILS, LEAD_ROLE);

    // Type a note
    const textarea = screen.getByLabelText(/note \(optional\)/i);
    await user.type(textarea, "legit");

    // Click Confirm
    await user.click(screen.getByRole("button", { name: /confirm/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/brand/matches/match-fts-001"),
        expect.objectContaining({
          method: "PATCH",
          body: expect.stringContaining('"lifecycle_status":"confirmed"'),
        }),
      );
    });

    // Note is embedded in the PATCH body
    const calls = vi.mocked(globalThis.fetch).mock.calls;
    const patchCall = calls.find(
      ([url]) => typeof url === "string" && url.includes("/brand/matches/match-fts-001"),
    );
    expect(patchCall).toBeDefined();
    const body = patchCall?.[1]?.body as string | undefined;
    expect(body).toContain('"note":"legit"');
  });

  // ---- Note max length + counter -------------------------------------------

  it("test_note_max_500: textarea has maxLength attribute of 500", () => {
    renderDrawer(FTS_MATCH, FTS_DETAILS, LEAD_ROLE);

    const textarea = screen.getByLabelText(/note \(optional\)/i);
    expect(textarea).toHaveAttribute("maxLength", "500");
  });

  it("test_note_counter: typing 'abc' shows '3/500' counter", async () => {
    const user = userEvent.setup();
    renderDrawer(FTS_MATCH, FTS_DETAILS, LEAD_ROLE);

    const textarea = screen.getByLabelText(/note \(optional\)/i);
    await user.type(textarea, "abc");

    expect(screen.getByText("3/500")).toBeInTheDocument();
  });
});
