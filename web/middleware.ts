import { auth } from "@/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const session = req.auth;
  const { pathname, origin } = req.nextUrl;

  // 1. Unauthenticated on a matched route -> /login?next=<path>
  if (!session) {
    const loginUrl = new URL("/login", origin);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // 2. must_change_password: block every route except /change-password and /api/auth/*
  const user = (session.user as any) ?? {};
  if (user.must_change_password && pathname !== "/change-password") {
    const u = new URL("/change-password", origin);
    u.searchParams.set("reason", "first_login");
    return NextResponse.redirect(u);
  }

  // 3. Dashboard role mismatch: redirect, not deny.
  const dashboardRoles: string[] = Array.isArray(user.dashboard_roles)
    ? user.dashboard_roles
    : [];

  if (pathname.startsWith("/red") && !dashboardRoles.includes("red")) {
    if (dashboardRoles.includes("blue")) {
      return NextResponse.redirect(new URL("/blue", origin));
    }
    return NextResponse.redirect(new URL("/", origin));
  }

  if (pathname.startsWith("/blue") && !dashboardRoles.includes("blue")) {
    if (dashboardRoles.includes("red")) {
      return NextResponse.redirect(new URL("/red", origin));
    }
    return NextResponse.redirect(new URL("/", origin));
  }

  return NextResponse.next();
});

export const config = {
  matcher: [
    "/red/:path*",
    "/blue/:path*",
    "/events/:path*",
    "/sources/:path*",
    "/webhooks/:path*",
    "/admin/:path*",
  ],
};
