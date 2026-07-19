"use client";

import type { FeedType } from "@/app/api-client";
import { Badge } from "@/components/ui/badge";

// Brand: neutral Mist background + Deep teal text for all feed types.
// Type isn't a status - no need to overload color semantics. Letter variance alone differentiates.
const TYPE_STYLE = {
  bg: "rgba(159, 225, 203, 0.12)",
  fg: "#9FE1CB",
  border: "#0F6E56",
};

export function TypeBadge({ feed_type }: { feed_type: FeedType }) {
  return (
    <Badge
      variant="outline"
      className="brand-caption"
      style={{
        backgroundColor: TYPE_STYLE.bg,
        color: TYPE_STYLE.fg,
        borderColor: TYPE_STYLE.border,
      }}
    >
      {feed_type.toUpperCase()}
    </Badge>
  );
}
