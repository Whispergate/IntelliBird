// Owned by: 12.1-05-PLAN
// Production tests — replace Wave 0 stubs (plan 12.1-05a).

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { AssetSummaryCards } from "../../app/projects/[id]/assets/components/AssetSummaryCards";
import type { AssetSummaryMap } from "../../app/projects/[id]/assets/AssetsClient";

function makeSummary(overrides: Partial<AssetSummaryMap> = {}): AssetSummaryMap {
  return {
    DOMAINS: { count: 12, stale_count: 0 },
    IPS: { count: 7, stale_count: 2 },
    OPEN_PORTS: { count: 5, stale_count: 0 },
    URLS: { count: 3, stale_count: 0 },
    TECHNOLOGIES: { count: 2, stale_count: 1 },
    IDENTITIES: { count: 0, stale_count: 0 },
    OTHER: { count: 1, stale_count: 0 },
    ...overrides,
  };
}

describe("AssetSummaryCards", () => {
  it("renders all 7 bucket cards when summary has all keys", () => {
    render(
      <AssetSummaryCards
        summary={makeSummary()}
        activeBucket={null}
        onBucketClick={vi.fn()}
      />,
    );

    // Byte-exact labels per UI-SPEC Copywriting Contract.
    for (const label of [
      "DOMAINS",
      "IPS",
      "OPEN PORTS",
      "URLS",
      "TECHNOLOGIES",
      "IDENTITIES",
      "OTHER",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it("renders all 7 cards even when every count is 0 (cards never disappear)", () => {
    const zeroSummary: AssetSummaryMap = Object.fromEntries(
      ["DOMAINS", "IPS", "OPEN_PORTS", "URLS", "TECHNOLOGIES", "IDENTITIES", "OTHER"].map(
        (k) => [k, { count: 0, stale_count: 0 }],
      ),
    );
    render(
      <AssetSummaryCards
        summary={zeroSummary}
        activeBucket={null}
        onBucketClick={vi.fn()}
      />,
    );
    const cards = screen.getAllByRole("button");
    // 7 summary cards rendered (Card with role=button).
    expect(cards.length).toBe(7);
  });

  it("omits stale sub-count when stale_count === 0", () => {
    render(
      <AssetSummaryCards
        summary={makeSummary({ DOMAINS: { count: 12, stale_count: 0 } })}
        activeBucket={null}
        onBucketClick={vi.fn()}
      />,
    );
    // DOMAINS has zero stale → no stale indicator rendered for that bucket.
    expect(screen.queryByTestId("asset-summary-card-DOMAINS-stale")).toBeNull();
    // IPS has stale_count=2 → stale indicator rendered.
    expect(screen.getByTestId("asset-summary-card-IPS-stale").textContent).toContain("2 stale");
  });

  it("fires onBucketClick(bucketKey) when a card is clicked", () => {
    const onBucketClick = vi.fn();
    render(
      <AssetSummaryCards
        summary={makeSummary()}
        activeBucket={null}
        onBucketClick={onBucketClick}
      />,
    );
    fireEvent.click(screen.getByTestId("asset-summary-card-DOMAINS"));
    expect(onBucketClick).toHaveBeenCalledWith("DOMAINS");
    fireEvent.click(screen.getByTestId("asset-summary-card-OPEN_PORTS"));
    expect(onBucketClick).toHaveBeenCalledWith("OPEN_PORTS");
  });

  it("applies ring-2 focus ring to the active card", () => {
    render(
      <AssetSummaryCards
        summary={makeSummary()}
        activeBucket="IPS"
        onBucketClick={vi.fn()}
      />,
    );
    const activeCard = screen.getByTestId("asset-summary-card-IPS");
    expect(activeCard.className).toContain("ring-2");
    const inactiveCard = screen.getByTestId("asset-summary-card-DOMAINS");
    expect(inactiveCard.className).not.toContain("ring-2");
  });

  it("renders loading skeleton when summary is null", () => {
    render(
      <AssetSummaryCards
        summary={null}
        activeBucket={null}
        onBucketClick={vi.fn()}
      />,
    );
    expect(screen.getByTestId("asset-summary-cards-loading")).toBeTruthy();
  });
});
