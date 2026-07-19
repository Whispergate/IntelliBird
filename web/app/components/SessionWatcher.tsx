"use client";

import { useEffect } from "react";
import { signOut, useSession } from "next-auth/react";

export function SessionWatcher() {
  const { data: session } = useSession();
  useEffect(() => {
    if ((session as any)?.error === "AccessTokenExpired") {
      signOut({ callbackUrl: "/login?reason=expired" });
    }
  }, [session]);
  return null;
}
