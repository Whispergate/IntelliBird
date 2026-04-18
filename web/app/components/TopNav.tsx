"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useRole } from "@/app/lib/role-context";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

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
      {/* Logo / wordmark */}
      <Link
        href={dashboardHref}
        className="brand-heading shrink-0"
        style={{ color: "var(--brand-primary)", textDecoration: "none" }}
      >
        IntelliBird
      </Link>

      {/* Dashboard nav link */}
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

      {/* Sources nav link */}
      <Link
        href="/sources"
        className={`${linkBase} ${isActive("/sources") ? linkActiveClass : linkInactive}`}
        style={
          isActive("/sources")
            ? {
                color: "var(--brand-primary)",
                borderColor: "var(--brand-primary)",
              }
            : { color: "var(--brand-fog)" }
        }
        aria-current={isActive("/sources") ? "page" : undefined}
      >
        Sources
      </Link>

      {/* Events nav link */}
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

      {/* Webhooks nav link */}
      <Link
        href="/webhooks"
        className={`${linkBase} ${isActive("/webhooks") ? linkActiveClass : linkInactive}`}
        style={
          isActive("/webhooks")
            ? {
                color: "var(--brand-primary)",
                borderColor: "var(--brand-primary)",
              }
            : { color: "var(--brand-fog)" }
        }
        aria-current={isActive("/webhooks") ? "page" : undefined}
      >
        Webhooks
      </Link>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Role pill + dropdown */}
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
          <DropdownMenuItem onClick={() => router.push("/sources")}>
            Sources
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </nav>
  );
}
