import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DashboardShell } from "@/app/components/DashboardShell";
import { useRole } from "@/app/lib/role-context";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/blue",
  useSearchParams: () => new URLSearchParams(),
}));

function RoleProbe() {
  const role = useRole();
  return <div data-testid="role-probe">{role}</div>;
}

describe("DashboardShell", () => {
  it("renders TopNav and mounts children inside the bottom-half slot", () => {
    render(
      <DashboardShell role="blue">
        <div data-testid="child">child-content</div>
      </DashboardShell>,
    );
    expect(
      screen.getByRole("navigation", { name: /Main navigation/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-bottom-half")).toBeInTheDocument();
    expect(screen.getByTestId("child")).toHaveTextContent("child-content");
  });

  it("provides the role context value to descendants (blue)", () => {
    render(
      <DashboardShell role="blue">
        <RoleProbe />
      </DashboardShell>,
    );
    expect(screen.getByTestId("role-probe")).toHaveTextContent("blue");
  });

  it("provides the role context value to descendants (red)", () => {
    render(
      <DashboardShell role="red">
        <RoleProbe />
      </DashboardShell>,
    );
    expect(screen.getByTestId("role-probe")).toHaveTextContent("red");
  });

  it("renders DesktopRequiredBanner (hidden at >=1024px via CSS)", () => {
    render(<DashboardShell role="blue">{null}</DashboardShell>);
    expect(
      screen.getByText(
        "IntelliBird dashboards require a viewport of at least 1024px. Please open on a desktop browser.",
      ),
    ).toBeInTheDocument();
  });

  it("renders the geomap bleed wrapper with negative horizontal margin", () => {
    render(<DashboardShell role="blue">{null}</DashboardShell>);
    const bleed = screen.getByTestId("geomap-bleed");
    expect(bleed).toHaveStyle({ margin: "0 -1.5rem" });
  });
});
