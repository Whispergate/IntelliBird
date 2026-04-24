import "./globals.css";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/sonner";
import { NoAuthBanner } from "./components/NoAuthBanner";
import { AppHeader } from "./components/AppHeader";
import { fetchSystemStatus } from "./api-client";
import { Providers } from "./providers";

export const metadata = {
  title: "IntelliBird",
  description: "Self-hosted threat intelligence platform",
  icons: {
    icon: "/brand/bird.svg",
    shortcut: "/brand/bird.svg",
    apple: "/brand/bird.svg",
  },
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
        <Providers>
          <NoAuthBanner status={status} />
          {/* Global TopNav (suppresses on /login, /setup, /change-password).
              DashboardShell no longer emits its own TopNav. */}
          <AppHeader />
          <main style={{ padding: "1.5rem" }}>{children}</main>
          <Toaster richColors position="top-right" />
        </Providers>
      </body>
    </html>
  );
}
