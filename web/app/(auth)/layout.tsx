import type { ReactNode } from "react";

/**
 * Auth route group layout. Intentionally minimal — no DashboardShell, no TopNav.
 * The root layout already renders <NoAuthBanner /> above all children, which
 * includes the auth pages. This layout centers the auth card in the viewport.
 */
export default function AuthGroupLayout({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-[400px]">{children}</div>
    </main>
  );
}
