import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TopNav } from "@/app/components/TopNav";
import { RoleProvider } from "@/app/lib/role-context";

const pushMock = vi.fn();
let pathnameMock = "/blue";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  usePathname: () => pathnameMock,
}));

beforeEach(() => {
  pushMock.mockClear();
  pathnameMock = "/blue";
});

describe("TopNav — Webhooks link", () => {
  it("renders 'Webhooks' link with href='/webhooks' after Events link", () => {
    render(
      <RoleProvider value="blue">
        <TopNav />
      </RoleProvider>,
    );
    const webhooksLink = screen.getByRole("link", { name: "Webhooks" });
    expect(webhooksLink).toBeDefined();
    expect(webhooksLink.getAttribute("href")).toBe("/webhooks");

    // Verify it appears after Events link in the DOM
    const allLinks = screen.getAllByRole("link");
    const eventsIdx = allLinks.findIndex((l) => l.textContent === "Events");
    const webhooksIdx = allLinks.findIndex((l) => l.textContent === "Webhooks");
    expect(webhooksIdx).toBeGreaterThan(eventsIdx);
  });

  it("underlines with brand-primary when pathname === '/webhooks'", () => {
    pathnameMock = "/webhooks";
    render(
      <RoleProvider value="blue">
        <TopNav />
      </RoleProvider>,
    );
    const link = screen.getByRole("link", { name: "Webhooks" });
    expect(link.getAttribute("aria-current")).toBe("page");
    // Active links get border-b-2 class
    expect(link.className).toContain("border-b-2");
  });
});
