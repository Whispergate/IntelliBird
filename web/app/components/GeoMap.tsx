"use client";

import dynamic from "next/dynamic";
import type { GeoMapProps } from "./GeoMapImpl";

export type { GeoMapProps } from "./GeoMapImpl";

export const GeoMap = dynamic<GeoMapProps>(
  () => import("./GeoMapImpl").then((m) => m.GeoMapImpl),
  {
    ssr: false,
    loading: () => (
      <div
        data-testid="geomap-loading"
        className="animate-pulse"
        style={{
          height: "50vh",
          width: "100%",
          background: "hsl(var(--muted))",
        }}
      />
    ),
  },
);
