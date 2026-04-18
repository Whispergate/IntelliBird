"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    let target: "red" | "blue" = "blue";
    try {
      const last = window.localStorage.getItem("intellibird:last-role");
      if (last === "red" || last === "blue") target = last;
    } catch {
      // localStorage unavailable (Safari private mode, etc.) — default to blue
    }
    router.replace(`/${target}`);
  }, [router]);

  return (
    <div
      aria-live="polite"
      style={{ padding: "2rem", textAlign: "center", color: "var(--brand-slate)" }}
    >
      Redirecting...
    </div>
  );
}
