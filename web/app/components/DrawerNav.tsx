"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

export type DrawerNavProps = {
  currentIndex: number;
  totalCount: number;
  onPrev: () => void;
  onNext: () => void;
};

export function DrawerNav({
  currentIndex,
  totalCount,
  onPrev,
  onNext,
}: DrawerNavProps) {
  const prevDisabled = currentIndex <= 0;
  const nextDisabled = currentIndex >= totalCount - 1;

  return (
    <div
      data-testid="drawer-nav"
      className="flex items-center gap-1"
      role="group"
      aria-label="Event navigation"
    >
      <button
        type="button"
        aria-label="Previous event"
        aria-disabled={prevDisabled}
        disabled={prevDisabled}
        onClick={onPrev}
        className="inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
        style={{ minWidth: 28, minHeight: 28 }}
      >
        <ChevronLeft size={16} />
      </button>
      <span className="text-xs text-muted-foreground tabular-nums">
        {totalCount === 0 ? "0 / 0" : `${currentIndex + 1} / ${totalCount}`}
      </span>
      <button
        type="button"
        aria-label="Next event"
        aria-disabled={nextDisabled}
        disabled={nextDisabled}
        onClick={onNext}
        className="inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed"
        style={{ minWidth: 28, minHeight: 28 }}
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}
