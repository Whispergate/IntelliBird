import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RoleProvider } from "@/app/lib/role-context";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/blue",
}));

vi.mock("@/app/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/app/api-client")>(
    "@/app/api-client",
  );
  return {
    ...actual,
    listEvents: vi.fn().mockResolvedValue({ items: [], next_cursor: null, total: null }),
  };
});

import * as apiClient from "@/app/api-client";
import { BlueWidgets, RedWidgets } from "@/app/components/widgets";
import { WidgetErrorBoundary } from "@/app/components/widgets/WidgetErrorBoundary";
import { WidgetCard } from "@/app/components/widgets/WidgetCard";

const listEventsMock = apiClient.listEvents as ReturnType<typeof vi.fn>;

beforeEach(() => {
  listEventsMock.mockReset();
  listEventsMock.mockResolvedValue({ items: [], next_cursor: null, total: null });
});

describe("widgets", () => {
  it("BlueWidgets renders 3 blue widget labels", async () => {
    render(
      <RoleProvider value="blue">
        <BlueWidgets />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("INCOMING IOCs (24H)")).toBeInTheDocument();
    });
    expect(screen.getByText("CVEs CVSS \u2265 7.0 (7D)")).toBeInTheDocument();
    expect(screen.getByText("VENDOR ADVISORIES (24H)")).toBeInTheDocument();
  });

  it("RedWidgets renders 3 red widget labels", async () => {
    render(
      <RoleProvider value="red">
        <RedWidgets />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText("ACTOR INFRASTRUCTURE (24H)")).toBeInTheDocument();
    });
    expect(screen.getByText("FRESH EXPLOITS (7D)")).toBeInTheDocument();
    expect(screen.getByText("TOOLING CHATTER (24H)")).toBeInTheDocument();
  });

  it("widget zero state renders verbatim copy", async () => {
    render(
      <RoleProvider value="blue">
        <BlueWidgets />
      </RoleProvider>,
    );
    await waitFor(() => {
      const zeroStates = screen.getAllByText(
        "No data yet. Register sources and wait for polls.",
      );
      expect(zeroStates.length).toBe(3);
    });
  });

  it("widget calls listEvents with role header from context", async () => {
    render(
      <RoleProvider value="red">
        <RedWidgets />
      </RoleProvider>,
    );
    await waitFor(() => {
      expect(listEventsMock).toHaveBeenCalled();
    });
    // Every call should pass "red" as second argument.
    for (const call of listEventsMock.mock.calls) {
      expect(call[1]).toBe("red");
    }
  });

  it("WidgetErrorBoundary renders verbatim fallback copy when child throws", () => {
    const Bomb = () => {
      throw new Error("boom");
    };
    render(
      <WidgetErrorBoundary label="Test">
        <Bomb />
      </WidgetErrorBoundary>,
    );
    expect(
      screen.getByText("Widget unavailable. Check console."),
    ).toBeInTheDocument();
  });

  it("WidgetCard renders the count number in text-3xl font-semibold", () => {
    render(<WidgetCard label="TEST" count={42} loading={false} />);
    const count = screen.getByTestId("widget-count");
    expect(count).toHaveTextContent("42");
    expect(count).toHaveClass("text-3xl");
    expect(count).toHaveClass("font-semibold");
  });

  it("widget passes limit 1000 not 200 per D-16", async () => {
    render(
      <RoleProvider value="blue">
        <BlueWidgets />
      </RoleProvider>,
    );
    await waitFor(() => expect(listEventsMock).toHaveBeenCalled());
    for (const call of listEventsMock.mock.calls) {
      expect(call[0].limit).toBe(1000);
    }
  });

  it("ActorInfra and ToolingChatter opt into tag_mode=any", async () => {
    render(
      <RoleProvider value="red">
        <RedWidgets />
      </RoleProvider>,
    );
    await waitFor(() => expect(listEventsMock).toHaveBeenCalled());
    const actorCalls = listEventsMock.mock.calls.filter(
      (c) => Array.isArray(c[0].tag) && c[0].tag.includes("actor"),
    );
    expect(actorCalls.length).toBeGreaterThan(0);
    for (const c of actorCalls) expect(c[0].tag_mode).toBe("any");

    const toolingCalls = listEventsMock.mock.calls.filter(
      (c) => Array.isArray(c[0].tag) && c[0].tag.includes("tooling"),
    );
    expect(toolingCalls.length).toBeGreaterThan(0);
    for (const c of toolingCalls) expect(c[0].tag_mode).toBe("any");
  });

  it("zero state renders Go to Sources CTA link", async () => {
    listEventsMock.mockResolvedValue({ items: [], next_cursor: null, total: null });
    render(
      <RoleProvider value="blue">
        <BlueWidgets />
      </RoleProvider>,
    );
    await waitFor(() => {
      const ctas = screen.getAllByText("Go to Sources \u2192");
      expect(ctas.length).toBeGreaterThan(0);
    });
  });
});
