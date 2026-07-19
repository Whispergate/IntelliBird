import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  ProjectRoleProvider,
  useProjectRole,
  type ProjectRoleString,
} from "@/app/projects/[id]/ProjectRoleProvider";

/**
 * Probe component: renders all boolean flags as data-testid attributes so
 * we can assert their values without the test knowing about implementation
 * internals beyond what useProjectRole() exposes.
 */
function Probe() {
  const { role, isAdmin, isLead, isContributor, isObserver } = useProjectRole();
  return (
    <div>
      <span data-testid="role">{role ?? "null"}</span>
      <span data-testid="isAdmin">{String(isAdmin)}</span>
      <span data-testid="isLead">{String(isLead)}</span>
      <span data-testid="isContributor">{String(isContributor)}</span>
      <span data-testid="isObserver">{String(isObserver)}</span>
    </div>
  );
}

function renderWithRole(role: ProjectRoleString) {
  render(
    <ProjectRoleProvider role={role}>
      <Probe />
    </ProjectRoleProvider>,
  );
}

describe("ProjectRoleProvider / useProjectRole", () => {
  it("Admin role: all flags true except isObserver", () => {
    renderWithRole("Admin");
    expect(screen.getByTestId("isAdmin").textContent).toBe("true");
    expect(screen.getByTestId("isLead").textContent).toBe("true");      // cascade
    expect(screen.getByTestId("isContributor").textContent).toBe("true"); // cascade
    expect(screen.getByTestId("isObserver").textContent).toBe("false");
    expect(screen.getByTestId("role").textContent).toBe("Admin");
  });

  it("Lead role: isLead + isContributor true; isAdmin + isObserver false", () => {
    renderWithRole("Lead");
    expect(screen.getByTestId("isAdmin").textContent).toBe("false");
    expect(screen.getByTestId("isLead").textContent).toBe("true");
    expect(screen.getByTestId("isContributor").textContent).toBe("true"); // cascade
    expect(screen.getByTestId("isObserver").textContent).toBe("false");
  });

  it("Contributor role: isContributor true; isLead + isAdmin + isObserver false", () => {
    renderWithRole("Contributor");
    expect(screen.getByTestId("isAdmin").textContent).toBe("false");
    expect(screen.getByTestId("isLead").textContent).toBe("false");
    expect(screen.getByTestId("isContributor").textContent).toBe("true");
    expect(screen.getByTestId("isObserver").textContent).toBe("false");
  });

  it("Observer role: isObserver true; all others false", () => {
    renderWithRole("Observer");
    expect(screen.getByTestId("isAdmin").textContent).toBe("false");
    expect(screen.getByTestId("isLead").textContent).toBe("false");
    expect(screen.getByTestId("isContributor").textContent).toBe("false");
    expect(screen.getByTestId("isObserver").textContent).toBe("true");
  });

  it("null role: isObserver true (least-privilege fallback); all others false", () => {
    renderWithRole(null);
    expect(screen.getByTestId("isAdmin").textContent).toBe("false");
    expect(screen.getByTestId("isLead").textContent).toBe("false");
    expect(screen.getByTestId("isContributor").textContent).toBe("false");
    expect(screen.getByTestId("isObserver").textContent).toBe("true");
    expect(screen.getByTestId("role").textContent).toBe("null");
  });

  it("useProjectRole throws when used outside ProjectRoleProvider", () => {
    // Suppress React's console.error for the expected thrown error.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(
      /within ProjectRoleProvider/i,
    );
    spy.mockRestore();
  });
});
