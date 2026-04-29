"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useRole } from "@/app/lib/role-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { CircleUser } from "lucide-react";
import { useSession } from "next-auth/react";
import React from "react";

const ROLE_BADGE_STYLES: Record<string, React.CSSProperties> = {
  Admin:   { background: "rgba(29,158,117,0.15)", border: "1px solid #1D9E75", color: "#1D9E75" },
  Analyst: { background: "rgba(159,225,203,0.20)", border: "1px solid #9FE1CB", color: "#9FE1CB" },
  Viewer:  { background: "rgba(136,135,128,0.15)", border: "1px solid #888780", color: "#888780" },
};

function RoleBadge({ role }: { role?: string }) {
  const style = ROLE_BADGE_STYLES[role ?? "Viewer"] ?? ROLE_BADGE_STYLES.Viewer;
  return (
    <span
      className="brand-caption h-5 px-3 inline-flex items-center rounded"
      style={style}
    >
      {role ?? "Viewer"}
    </span>
  );
}

async function onSignOut() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch {
    // ignore — proceed to redirect
  }
  window.location.href = "/login?reason=logged_out";
}

const BLUE_PILL_STYLE = {
  backgroundColor: "rgba(29, 158, 117, 0.15)",
  color: "#1D9E75",
  borderColor: "#1D9E75",
};

const RED_PILL_STYLE = {
  backgroundColor: "rgba(220, 38, 38, 0.15)",
  color: "hsl(var(--destructive))",
  borderColor: "hsl(var(--destructive))",
};

export function TopNav() {
  const role = useRole();
  const router = useRouter();
  const pathname = usePathname();
  const { data: session } = useSession();
  const user = (session?.user as any) ?? null;

  const dashboardHref = role === "red" ? "/red" : "/blue";
  const pillStyle = role === "red" ? RED_PILL_STYLE : BLUE_PILL_STYLE;
  const pillLabel = role === "red" ? "RED TEAM" : "BLUE TEAM";
  const switchTarget: "red" | "blue" = role === "red" ? "blue" : "red";
  const switchLabel =
    switchTarget === "red" ? "Switch to Red Team" : "Switch to Blue Team";

  // Role-tinted border-bottom overlay at 30% opacity
  const borderTint =
    role === "red"
      ? "inset 0 -1px 0 rgba(220, 38, 38, 0.30)"
      : "inset 0 -1px 0 rgba(29, 158, 117, 0.30)";

  function handleSwitch(target: "red" | "blue") {
    try {
      if (typeof window !== "undefined") {
        window.localStorage.setItem("intellibird:last-role", target);
      }
    } catch {
      // localStorage unavailable (Safari private mode, etc.) — navigation still works.
    }
    router.push(`/${target}`);
  }

  const linkBase =
    "inline-flex items-center h-11 px-4 transition-opacity";
  const linkInactive =
    "opacity-80 hover:opacity-100";
  const linkActiveClass =
    "opacity-100 border-b-2";

  const isActive = (href: string) => pathname === href;

  return (
    <nav
      role="navigation"
      aria-label="Main navigation"
      className="flex items-center gap-6 px-4"
      style={{
        height: "52px",
        background: "var(--brand-ink)",
        color: "var(--brand-fog)",
        borderBottom: "1px solid var(--brand-deep-teal)",
        boxShadow: borderTint,
      }}
    >
      {/* Logo / wordmark*/}
      <Link
        href={dashboardHref}
        className="shrink-0"
        aria-label="IntelliBird"
        style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}
      >
        <img
          src="/brand/text.svg"
          alt="IntelliBird"
          style={{ height: "108px", width: "auto", display: "block" }}
        />
      </Link>

      {/* Dashboard nav link*/}
      <Link
        href={dashboardHref}
        className={`${linkBase} ${isActive(dashboardHref) ? linkActiveClass : linkInactive}`}
        style={
          isActive(dashboardHref)
            ? {
                color: "var(--brand-primary)",
                borderColor: "var(--brand-primary)",
              }
            : { color: "var(--brand-fog)" }
        }
        aria-current={isActive(dashboardHref) ? "page" : undefined}
      >
        Dashboard
      </Link>

      {/* Projects nav link (active for any /projects/* path) */}
      <Link
        href="/projects"
        className={`${linkBase} ${pathname?.startsWith("/projects") ? linkActiveClass : linkInactive}`}
        style={
          pathname?.startsWith("/projects")
            ? {
                color: "var(--brand-primary)",
                borderColor: "var(--brand-primary)",
              }
            : { color: "var(--brand-fog)" }
        }
        aria-current={pathname?.startsWith("/projects") ? "page" : undefined}
      >
        Projects
      </Link>

      {/* Events nav link*/}
      <Link
        href="/events"
        className={`${linkBase} ${isActive("/events") ? linkActiveClass : linkInactive}`}
        style={
          isActive("/events")
            ? {
                color: "var(--brand-primary)",
                borderColor: "var(--brand-primary)",
              }
            : { color: "var(--brand-fog)" }
        }
        aria-current={isActive("/events") ? "page" : undefined}
      >
        Events
      </Link>

      {/* Spacer*/}
      <div className="flex-1" />

      {/* Role pill + dropdown*/}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Switch dashboard role, currently ${role}`}
            className="focus:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] rounded-full"
          >
            <Badge
              variant="outline"
              className="brand-caption h-6 px-3 cursor-pointer"
              style={pillStyle}
            >
              {pillLabel}
            </Badge>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => handleSwitch(switchTarget)}>
            {switchLabel}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Admin</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => router.push("/sources")}>
            Sources
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => router.push("/webhooks")}>
            Webhooks
          </DropdownMenuItem>
          {user?.role === "Admin" && (
            <DropdownMenuItem onClick={() => router.push("/admin/monitoring")}>
              Source Monitoring
            </DropdownMenuItem>
          )}
          {user?.role === "Admin" && (
            <DropdownMenuItem onClick={() => router.push("/admin/maintenance")}>
              Maintenance Windows
            </DropdownMenuItem>
          )}
          {user?.role === "Admin" && (
            <DropdownMenuItem onClick={() => router.push("/admin/ai-jobs")}>
              AI Jobs
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* CircleUser user menu — to the right of role pill */}
      {user && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label="User menu"
              className="ml-2"
            >
              <CircleUser size={24} style={{ color: "var(--brand-fog)" }} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[160px]">
            <DropdownMenuLabel className="flex flex-col gap-1 px-2 py-1.5">
              <span style={{ color: "var(--muted-foreground)" }}>{user.name}</span>
              <RoleBadge role={user.role} />
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {user.role === "Admin" && (
              <DropdownMenuItem onClick={() => router.push("/admin/users")}>
                User Management
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={onSignOut}>Sign out</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </nav>
  );
}
