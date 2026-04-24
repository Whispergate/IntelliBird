// Owned by: 12.1-05-PLAN
// Production tests — replace Wave 0 stubs (plan 12.1-05a).

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import {
  AssetsFilterBar,
  type AssetFilters,
} from "../../app/projects/[id]/assets/components/AssetsFilterBar";

function baseFilters(overrides: Partial<AssetFilters> = {}): AssetFilters {
  return {
    type: [],
    scope: [],
    stale: "show",
    module: [],
    first_seen_from: "",
    first_seen_to: "",
    last_seen_from: "",
    last_seen_to: "",
    scan_id: "",
    search: "",
    ...overrides,
  };
}

describe("AssetsFilterBar — multi-select trigger labels", () => {
  it("shows 'All types' / 'All scopes' / 'All modules' when none selected", () => {
    render(
      <AssetsFilterBar
        filters={baseFilters()}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={["DNS_NAME", "IP_ADDRESS"]}
        availableModules={["httpx", "dnsx"]}
        availableScans={[]}
      />,
    );
    expect(screen.getByTestId("assets-filter-type-trigger").textContent).toBe("All types");
    expect(screen.getByTestId("assets-filter-scope-trigger").textContent).toBe("All scopes");
    expect(screen.getByTestId("assets-filter-module-trigger").textContent).toBe("All modules");
  });

  it("shows the selected label when exactly 1 is selected", () => {
    render(
      <AssetsFilterBar
        filters={baseFilters({ type: ["DNS_NAME"], scope: ["in_scope"] })}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={["DNS_NAME", "IP_ADDRESS"]}
        availableModules={["httpx"]}
        availableScans={[]}
      />,
    );
    expect(screen.getByTestId("assets-filter-type-trigger").textContent).toBe("DNS_NAME");
    // Scope uses a label map — "in_scope" → "In scope".
    expect(screen.getByTestId("assets-filter-scope-trigger").textContent).toBe("In scope");
  });

  it("shows '{first} +{N-1}' when 2+ are selected", () => {
    render(
      <AssetsFilterBar
        filters={baseFilters({
          type: ["DNS_NAME", "IP_ADDRESS", "OPEN_TCP_PORT"],
          scope: ["in_scope", "unscoped"],
        })}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={["DNS_NAME", "IP_ADDRESS", "OPEN_TCP_PORT"]}
        availableModules={[]}
        availableScans={[]}
      />,
    );
    expect(screen.getByTestId("assets-filter-type-trigger").textContent).toBe("DNS_NAME +2");
    expect(screen.getByTestId("assets-filter-scope-trigger").textContent).toBe("In scope +1");
  });

  it("shows 'Loading…' on type/module triggers while option lists are null", () => {
    render(
      <AssetsFilterBar
        filters={baseFilters()}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={null}
        availableModules={null}
        availableScans={null}
      />,
    );
    expect(screen.getByTestId("assets-filter-type-trigger").textContent).toBe("Loading…");
    expect(screen.getByTestId("assets-filter-module-trigger").textContent).toBe("Loading…");
  });
});

describe("AssetsFilterBar — Clear filters visibility", () => {
  it("is hidden when no filters are active", () => {
    render(
      <AssetsFilterBar
        filters={baseFilters()}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={[]}
        availableModules={[]}
        availableScans={[]}
      />,
    );
    expect(screen.queryByTestId("assets-filter-clear")).toBeNull();
  });

  it("is visible when at least one filter is active", () => {
    render(
      <AssetsFilterBar
        filters={baseFilters({ type: ["DNS_NAME"] })}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={["DNS_NAME"]}
        availableModules={[]}
        availableScans={[]}
      />,
    );
    const clearBtn = screen.getByTestId("assets-filter-clear");
    expect(clearBtn).toBeTruthy();
    expect(clearBtn.textContent).toBe("Clear filters");
  });

  it("fires onClear when clicked", () => {
    const onClear = vi.fn();
    render(
      <AssetsFilterBar
        filters={baseFilters({ search: "example.com" })}
        onChange={vi.fn()}
        onClear={onClear}
        availableTypes={[]}
        availableModules={[]}
        availableScans={[]}
      />,
    );
    fireEvent.click(screen.getByTestId("assets-filter-clear"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});

describe("AssetsFilterBar — Search submit on Enter", () => {
  it("fires onChange with search value when Enter is pressed", () => {
    const onChange = vi.fn();
    render(
      <AssetsFilterBar
        filters={baseFilters()}
        onChange={onChange}
        onClear={vi.fn()}
        availableTypes={[]}
        availableModules={[]}
        availableScans={[]}
      />,
    );
    const searchInput = screen.getByTestId("assets-filter-search") as HTMLInputElement;
    expect(searchInput.placeholder).toBe("Search target…");
    fireEvent.change(searchInput, { target: { value: "example.com" } });
    // Typing does NOT fire onChange (buffered locally).
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyDown(searchInput, { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(1);
    const emitted = onChange.mock.calls[0][0] as AssetFilters;
    expect(emitted.search).toBe("example.com");
  });
});

describe("AssetsFilterBar — Stale single-select", () => {
  it("defaults the Stale trigger label to 'Show all' and reflects current value on change", () => {
    // Radix Select's portal + pointerCapture behaviour is not friendly to jsdom;
    // rather than poking the popover, we verify the trigger reflects each of the
    // three canonical values. Source review ensures the three <SelectItem> values
    // and labels are present; see AssetsFilterBar.tsx.
    const { rerender } = render(
      <AssetsFilterBar
        filters={baseFilters()}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={[]}
        availableModules={[]}
        availableScans={[]}
      />,
    );
    expect(screen.getByTestId("assets-filter-stale-trigger").textContent).toBe("Show all");

    rerender(
      <AssetsFilterBar
        filters={baseFilters({ stale: "hide" })}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={[]}
        availableModules={[]}
        availableScans={[]}
      />,
    );
    expect(screen.getByTestId("assets-filter-stale-trigger").textContent).toBe("Hide stale");

    rerender(
      <AssetsFilterBar
        filters={baseFilters({ stale: "only" })}
        onChange={vi.fn()}
        onClear={vi.fn()}
        availableTypes={[]}
        availableModules={[]}
        availableScans={[]}
      />,
    );
    expect(screen.getByTestId("assets-filter-stale-trigger").textContent).toBe("Only stale");
  });
});
