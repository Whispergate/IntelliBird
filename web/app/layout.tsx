import "./globals.css";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/sonner";
import { NoAuthBanner } from "./components/NoAuthBanner";
import { OllamaHealthBanner } from "./components/OllamaHealthBanner";
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

async function fetchOllamaHealth(): Promise<"healthy" | "slow" | "down" | "unknown"> {
  try {
    const res = await fetch(
      `${process.env.API_BASE ?? process.env.NEXT_PUBLIC_API_BASE ?? "http://api:8000"}/api/admin/ai-health`,
      { cache: "no-store" },
    );
    if (!res.ok) return "unknown";
    const data = await res.json() as { ollama_health?: string };
    const h = data?.ollama_health;
    if (h === "slow" || h === "down" || h === "healthy") return h;
    return "unknown";
  } catch {
    return "unknown";
  }
}

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  const status = await fetchSystemStatus();
  // Fetch Ollama health for the app-shell banner.
  // Only show banner when AUTH is enabled (auth guard in place) — in dev-mode
  // without auth this is a trusted network, so suppress the banner to reduce noise.
  const ollamaHealth = status?.auth_enabled
    ? await fetchOllamaHealth()
    : "unknown";

  return (
    <html lang="en" className="dark">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif" }}>
        <Providers>
          <NoAuthBanner status={status} />
          <OllamaHealthBanner ollamaHealth={ollamaHealth} />
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
