"use client";

import { SessionProvider } from "next-auth/react";
import type { ReactNode } from "react";
import { SessionWatcher } from "./components/SessionWatcher";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SessionProvider refetchInterval={60} refetchOnWindowFocus>
      <SessionWatcher />
      {children}
    </SessionProvider>
  );
}
