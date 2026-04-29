import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Authentik from "next-auth/providers/authentik";

// Backend URL used server-side for calling FastAPI (not reachable from browser).
// In Docker: http://api:8000. Local dev: http://127.0.0.1:8000.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

type BackendUser = {
  id: string;
  username: string;
  role: "Admin" | "Analyst" | "Viewer";
  dashboard_roles: string[];
  must_change_password: boolean;
};

type BackendTokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
  user: BackendUser;
};

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      credentials: {
        username: { label: "Username" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const res = await fetch(`${BACKEND_URL}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: credentials?.username,
            password: credentials?.password,
          }),
        });
        if (!res.ok) {
          // Propagate backend error detail so the /login page can show the right toast.
          if (res.status === 429) {
            const retryAfter = res.headers.get("Retry-After") ?? "";
            throw new Error(`lockout:${retryAfter}`);
          }
          return null;
        }
        const body: BackendTokenResponse = await res.json();
        // NextAuth User is the shape passed to jwt callback; we piggyback the tokens.
        return {
          id: body.user.id,
          name: body.user.username,
          access_token: body.access_token,
          refresh_token: body.refresh_token,
          role: body.user.role,
          dashboard_roles: body.user.dashboard_roles,
          must_change_password: body.user.must_change_password,
          // expires_in used in jwt callback below
          access_expires_in: body.expires_in,
        } as any;
      },
    }),
    Authentik({
      clientId: process.env.SSO_CLIENT_ID ?? "",
      clientSecret: process.env.SSO_CLIENT_SECRET ?? "",
      issuer: process.env.SSO_ISSUER_URL ?? "",
    }),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.accessToken = (user as any).access_token;
        token.refreshToken = (user as any).refresh_token;
        token.role = (user as any).role;
        token.dashboardRoles = (user as any).dashboard_roles;
        token.mustChangePassword = (user as any).must_change_password;
        token.userId = (user as any).id;
        token.username = (user as any).name;
        const expiresIn = Number((user as any).access_expires_in) || 0;
        token.accessTokenExpires = expiresIn > 0
          ? Date.now() + expiresIn * 1000
          : 0;
      }
      // Mark expired so session callback can null the user out.
      if (
        typeof token.accessTokenExpires === "number" &&
        token.accessTokenExpires > 0 &&
        Date.now() >= token.accessTokenExpires
      ) {
        (token as any).error = "AccessTokenExpired";
      }
      return token;
    },
    async session({ session, token }) {
      if ((token as any).error === "AccessTokenExpired") {
        (session as any).error = "AccessTokenExpired";
        (session as any).accessToken = undefined;
        return session;
      }
      (session.user as any) = {
        id: token.userId as string,
        name: token.username as string,
        role: token.role as string,
        dashboard_roles: (token.dashboardRoles as string[]) ?? [],
        must_change_password: Boolean(token.mustChangePassword),
      };
      (session as any).accessToken = token.accessToken;
      return session;
    },
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
});
