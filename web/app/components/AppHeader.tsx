"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { RoleProvider, type DashboardRole } from "@/app/lib/role-context";
import { TopNav } from "./TopNav";

const SUPPRESS_PREFIXES = ["/login", "/setup", "/change-password"];

export function AppHeader() {
  const pathname = usePathname();
  const [role, setRole] = useState<DashboardRole>("blue");

  useEffect(() => {
    try {
      const last = window.localStorage.getItem("intellibird:last-role");
      if (last === "red" || last === "blue") setRole(last);
    } catch {
      // localStorage unavailable
    }
  }, [pathname]);

  if (SUPPRESS_PREFIXES.some((p) => pathname?.startsWith(p))) return null;

  return (
    <RoleProvider value={role}>
      <TopNav />
    </RoleProvider>
  );
}
