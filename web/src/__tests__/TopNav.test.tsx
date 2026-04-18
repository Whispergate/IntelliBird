import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  window.localStorage.clear();
});

describe("TopNav", () => {
  it("renders BLUE TEAM pill and Switch to Red Team dropdown item when role=blue", async () => {
    render(
      <RoleProvider value="blue">
        <TopNav />
      </RoleProvider>,
    );
    expect(screen.getByText("BLUE TEAM")).toBeInTheDocument();
    const trigger = screen.getByRole("button", {
      name: /Switch dashboard role, currently blue/i,
    });
    await userEvent.click(trigger);
    expect(await screen.findByText("Switch to Red Team")).toBeInTheDocument();
    // At least one "Sources" item exists (nav link + dropdown item both render)
    expect(screen.getAllByText("Sources").length).toBeGreaterThan(0);
  });

  it("renders RED TEAM pill and Switch to Blue Team dropdown item when role=red", async () => {
    render(
      <RoleProvider value="red">
        <TopNav />
      </RoleProvider>,
    );
    expect(screen.getByText("RED TEAM")).toBeInTheDocument();
    const trigger = screen.getByRole("button", {
      name: /Switch dashboard role, currently red/i,
    });
    await userEvent.click(trigger);
    expect(await screen.findByText("Switch to Blue Team")).toBeInTheDocument();
  });

  it("clicking Switch to Red Team navigates and persists last-role in localStorage", async () => {
    render(
      <RoleProvider value="blue">
        <TopNav />
      </RoleProvider>,
    );
    const trigger = screen.getByRole("button", {
      name: /Switch dashboard role, currently blue/i,
    });
    await userEvent.click(trigger);
    const item = await screen.findByText("Switch to Red Team");
    await userEvent.click(item);
    expect(pushMock).toHaveBeenCalledWith("/red");
    expect(window.localStorage.getItem("intellibird:last-role")).toBe("red");
  });

  it("renders IntelliBird wordmark and Sources link", () => {
    render(
      <RoleProvider value="blue">
        <TopNav />
      </RoleProvider>,
    );
    const wordmark = screen.getByRole("link", { name: "IntelliBird" });
    expect(wordmark).toHaveAttribute("href", "/blue");
    const sources = screen.getAllByRole("link").find((l) => l.textContent === "Sources");
    expect(sources).toHaveAttribute("href", "/sources");
  });

  it("test_topnav_has_events_link — Events link with href=/events is present", () => {
    render(
      <RoleProvider value="blue">
        <TopNav />
      </RoleProvider>,
    );
    const eventsLink = screen.getByRole("link", { name: "Events" });
    expect(eventsLink).toHaveAttribute("href", "/events");
  });

  it("test_topnav_events_link_is_active_on_events_route — active className applied on /events", () => {
    pathnameMock = "/events";
    render(
      <RoleProvider value="blue">
        <TopNav />
      </RoleProvider>,
    );
    const eventsLink = screen.getByRole("link", { name: "Events" });
    // Active links get "opacity-100 border-b-2" classes
    expect(eventsLink.className).toContain("border-b-2");
  });
});
