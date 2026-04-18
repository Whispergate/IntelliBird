"use client";

import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sparkline } from "./Sparkline";

type WidgetCardProps = {
  label: string;
  count: number | null;
  sparkline?: number[] | null;
  loading?: boolean;
  onClick?: () => void;
};

export function WidgetCard({ label, count, sparkline, loading, onClick }: WidgetCardProps) {
  const clickable = onClick !== undefined;

  return (
    <Card
      role={clickable ? "button" : "region"}
      tabIndex={clickable ? 0 : undefined}
      aria-label={label}
      className={`flex flex-col gap-2 p-4${clickable ? " cursor-pointer" : ""}`}
      style={{ minHeight: 120 }}
      onClick={clickable ? onClick : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <CardHeader className="p-0">
        <CardTitle className="brand-caption text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0 flex flex-col gap-1">
        {loading ? (
          <div
            data-testid="widget-loading"
            className="animate-pulse bg-muted rounded h-8 w-16"
          />
        ) : (
          <>
            <span
              data-testid="widget-count"
              className="text-3xl font-semibold text-foreground"
            >
              {count ?? 0}
            </span>
            {count === 0 ? (
              <>
                <p
                  data-testid="widget-zero"
                  className="text-xs text-muted-foreground"
                  style={{ fontSize: 12 }}
                >
                  No data yet. Register sources and wait for polls.
                </p>
                <Link
                  href="/sources"
                  className="text-[#EF9F27] hover:underline"
                  style={{ fontSize: 12 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  Go to Sources →
                </Link>
              </>
            ) : sparkline && sparkline.length >= 2 ? (
              <Sparkline data={sparkline} />
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
