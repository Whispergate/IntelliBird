import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DesktopRequiredBanner } from "@/app/components/DesktopRequiredBanner";

describe("DesktopRequiredBanner", () => {
  it("renders the heading and verbatim body copy from UI-SPEC", () => {
    render(<DesktopRequiredBanner />);
    expect(screen.getByText("Desktop required")).toBeInTheDocument();
    expect(
      screen.getByText(
        "IntelliBird dashboards require a viewport of at least 1024px. Please open on a desktop browser.",
      ),
    ).toBeInTheDocument();
  });

  it("uses brand-heading class on the heading", () => {
    render(<DesktopRequiredBanner />);
    const heading = screen.getByText("Desktop required");
    expect(heading).toHaveClass("brand-heading");
  });

  it("sets role=alert for screen readers", () => {
    render(<DesktopRequiredBanner />);
    const banner = screen.getByRole("alert");
    expect(banner).toBeInTheDocument();
  });
});
