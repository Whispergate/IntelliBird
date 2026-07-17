/**
 * EventsExportButton.test.tsx — (UX-02)
 *
 * Tests that the Export button in OverviewClient is hidden for Observer role
 * and visible for non-Observer roles (Lead, Contributor, Admin).
 *
 * Note: The PLAN referenced EventsClient.tsx but the actual Export button
 * lives in OverviewClient.tsx (the project-level header per UI-SPEC §PRJ-07).
 * This test file covers the OverviewClient Export button gate.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  ProjectRoleProvider,
  type ProjectRoleString,
} from "@/app/projects/[id]/ProjectRoleProvider";

// ---------------------------------------------------------------------------
// Mocks — must be hoisted before component imports
// ---------------------------------------------------------------------------

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/projects/test-id",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock api calls made in OverviewClient (listMemberships, listProjectSources)
vi.mock("@/app/projects/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/app/projects/lib/api")>(
    "@/app/projects/lib/api",
  );
  return {
    ...actual,
    listMemberships: vi.fn().mockResolvedValue([]),
    listProjectSources: vi.fn().mockResolvedValue([]),
  };
});

import { OverviewClient } from "@/app/projects/[id]/OverviewClient";
import type { ProjectResponse } from "@/app/projects/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MOCK_PROJECT: ProjectResponse = {
  id: "proj-test-id",
  name: "Test Project",
  engagement_type: "internal",
  description: "A test project",
  archived: false,
  created_by: "test-user",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  member_count: 1,
  active_scans_authorised: false,
  scope_acknowledgement_text: null,
  active_auth_confirmed_at: null,
  active_auth_confirmed_by: null,
  creator_is_current_user: false,
};

function renderOverviewWithRole(role: ProjectRoleString) {
  render(
    <ProjectRoleProvider role={role}>
      <OverviewClient project={MOCK_PROJECT} />
    </ProjectRoleProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OverviewClient Export button — UX-02 Observer gate", () => {
  it("Export button is hidden when role is Observer", () => {
    renderOverviewWithRole("Observer");
    expect(
      screen.queryByRole("button", { name: /export/i }),
    ).not.toBeInTheDocument();
  });

  it("Export button is hidden when role is null (least-privilege fallback)", () => {
    renderOverviewWithRole(null);
    expect(
      screen.queryByRole("button", { name: /export/i }),
    ).not.toBeInTheDocument();
  });

  it("Export button is visible when role is Lead", () => {
    renderOverviewWithRole("Lead");
    expect(
      screen.getByRole("button", { name: /export/i }),
    ).toBeInTheDocument();
  });

  it("Export button is visible when role is Contributor", () => {
    renderOverviewWithRole("Contributor");
    expect(
      screen.getByRole("button", { name: /export/i }),
    ).toBeInTheDocument();
  });

  it("Export button is visible when role is Admin", () => {
    renderOverviewWithRole("Admin");
    expect(
      screen.getByRole("button", { name: /export/i }),
    ).toBeInTheDocument();
  });
});
