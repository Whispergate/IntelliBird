import "./globals.css";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/sonner";
import { NoAuthBanner } from "./components/NoAuthBanner";
import { fetchSystemStatus } from "./api-client";

export const metadata = {
  title: "IntelliBird M1",
  description: "Self-hosted threat intelligence platform",
};

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  const status = await fetchSystemStatus();

  return (
    <html lang="en" className="dark">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif" }}>
        <NoAuthBanner status={status} />
        {/* TopNav is rendered per-route: DashboardShell provides a role-aware TopNav
            for /red and /blue. Routes that need nav (e.g. /sources) render their own
            shell or are served by a dedicated layout in a future phase. */}
        <main style={{ padding: "1.5rem" }}>{children}</main>
        <Toaster richColors position="top-right" />
      </body>
    </html>
  );
}
