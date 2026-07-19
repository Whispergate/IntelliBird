"use client";

/**
 * AssetSummaryCards - (UI-SPEC §Surface 3).
 *
 * Renders 7 bucket cards in stable order even when count=0.
 * Click fires onBucketClick(bucketKey); active bucket gets ring-2 focus ring.
 * Stale sub-count omitted when stale_count === 0.
 */

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { AssetSummaryMap } from "../AssetsClient";

/** Bucket iteration order - UI-SPEC locked. */
const BUCKET_ORDER = [
  "DOMAINS",
  "IPS",
  "OPEN_PORTS",
  "URLS",
  "TECHNOLOGIES",
  "IDENTITIES",
  "OTHER",
] as const;

/**
 * Human-readable labels per UI-SPEC Copywriting Contract (byte-exact).
 * "OPEN_PORTS" bucket key → "OPEN PORTS" label (space, not underscore).
 */
const BUCKET_LABELS: Record<(typeof BUCKET_ORDER)[number], string> = {
  DOMAINS: "DOMAINS",
  IPS: "IPS",
  OPEN_PORTS: "OPEN PORTS",
  URLS: "URLS",
  TECHNOLOGIES: "TECHNOLOGIES",
  IDENTITIES: "IDENTITIES",
  OTHER: "OTHER",
};

export interface AssetSummaryCardsProps {
  /** Null while loading. Empty object {} = loaded with zero data. */
  summary: AssetSummaryMap | null;
  /** Currently-active bucket (single-type-filter exact-match); null otherwise. */
  activeBucket: string | null;
  onBucketClick: (bucketKey: string) => void;
}

export function AssetSummaryCards({
  summary,
  activeBucket,
  onBucketClick,
}: AssetSummaryCardsProps) {
  // Loading skeleton - 7 pulse blocks with the same dimensions as real cards.
  if (summary === null) {
    return (
      <div
        className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4"
        data-testid="asset-summary-cards-loading"
      >
        {BUCKET_ORDER.map((k) => (
          <div
            key={k}
            className="animate-pulse bg-muted/40 h-[88px] rounded-md"
          />
        ))}
      </div>
    );
  }

  return (
    <div
      className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4"
      data-testid="asset-summary-cards"
    >
      {BUCKET_ORDER.map((key) => {
        const bucket = summary[key] ?? { count: 0, stale_count: 0 };
        const isActive = activeBucket === key;
        return (
          <Card
            key={key}
            role="button"
            tabIndex={0}
            aria-pressed={isActive}
            data-bucket={key}
            data-active={isActive ? "true" : "false"}
            data-testid={`asset-summary-card-${key}`}
            onClick={() => onBucketClick(key)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onBucketClick(key);
              }
            }}
            className={cn(
              "p-4 rounded-md border border-border bg-card cursor-pointer flex flex-col gap-1",
              isActive &&
                "ring-2 ring-ring ring-offset-2 ring-offset-background",
            )}
          >
            <span
              className="text-[12px] font-medium uppercase tracking-[0.15em] text-muted-foreground"
              style={{ lineHeight: 1 }}
            >
              {BUCKET_LABELS[key]}
            </span>
            <span
              className="text-[32px] font-medium text-foreground"
              style={{ lineHeight: 1.2 }}
            >
              {bucket.count}
            </span>
            {bucket.stale_count > 0 && (
              <span
                className="text-[12px] font-normal text-muted-foreground"
                data-testid={`asset-summary-card-${key}-stale`}
              >
                {bucket.stale_count} stale
              </span>
            )}
          </Card>
        );
      })}
    </div>
  );
}
