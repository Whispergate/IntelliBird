"use client";

import { Suspense, type ReactNode } from "react";
import { RoleProvider, type DashboardRole } from "@/app/lib/role-context";
import { TopNav } from "./TopNav";
import { DesktopRequiredBanner } from "./DesktopRequiredBanner";
import { GeoMap } from "./GeoMap";

type Props = {
  role: DashboardRole;
  children?: ReactNode;
};

export function DashboardShell({ role, children }: Props) {
  return (
    <RoleProvider value={role}>
      <div data-testid="dashboard-shell" data-role={role}>
        {/* TopNav breaks out of layout.tsx padding to reach full viewport width*/}
        <div style={{ margin: "-1.5rem -1.5rem 0" }}>
          <TopNav />
        </div>

        {/* Below 1024px: only DesktopRequiredBanner renders*/}
        <DesktopRequiredBanner />

        {/* Above 1024px: full dashboard*/}
        <div
          data-testid="dashboard-content"
          className="max-[1023px]:hidden block"
        >
          {/* GeoMap bleeds to the viewport edge via negative margin.*/}
          <div
            data-testid="geomap-bleed"
            style={{ margin: "0 -1.5rem", height: "50vh" }}
          >
            <Suspense
              fallback={
                <div
                  style={{
                    height: "50vh",
                    width: "100%",
                    background: "hsl(var(--muted))",
                  }}
                />
              }
            >
              <GeoMap height="50vh" />
            </Suspense>
          </div>

          {/* Bottom half slot — widgets + events list inject here from 05-04+05-05*/}
          <Suspense fallback={null}>
            <div
              data-testid="dashboard-bottom-half"
              style={{ paddingTop: "1.5rem" }}
            >
              {children}
            </div>
          </Suspense>
        </div>
      </div>
    </RoleProvider>
  );
}
