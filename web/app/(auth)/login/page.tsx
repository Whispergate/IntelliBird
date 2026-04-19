"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { toast } from "sonner";
import { Eye, EyeOff } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const reason = searchParams.get("reason");
    if (reason === "logged_out") {
      toast.info("Signed out", { duration: 3000 });
    } else if (reason === "expired") {
      toast.warning("Session expired", {
        description: "Sign in again to continue.",
        duration: 4000,
      });
    } else if (reason === "revoked") {
      toast.error("Session revoked", {
        description:
          "Your session was invalidated for security reasons. Sign in again.",
        duration: 6000,
      });
    }
  }, [searchParams]);

  useEffect(() => {
    fetch("/api/system/status")
      .then((r) => r.json())
      .then((s) => setSsoEnabled(Boolean(s.sso_enabled)))
      .catch(() => setSsoEnabled(false));
  }, []);

  const canSubmit = username.trim().length > 0 && password.length > 0 && !submitting;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const res = await signIn("credentials", {
      username,
      password,
      redirect: false,
    });
    setSubmitting(false);
    if (!res || res.error) {
      if (typeof res?.error === "string" && res.error.startsWith("lockout:")) {
        const secs = parseInt(res.error.split(":")[1] ?? "0", 10);
        const minutes = Math.max(1, Math.ceil(secs / 60));
        setError(`Account temporarily locked. Try again in ${minutes} minutes.`);
      } else {
        setError("Invalid username or password.");
      }
      return;
    }
    router.push(nextPath);
  }

  return (
    <>
      <h1
        className="brand-heading text-center mb-4"
        style={{ color: "var(--brand-primary)" }}
      >
        IntelliBird
      </h1>
      <Card className="p-6">
        <h2 className="brand-heading mb-6">Sign in</h2>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              name="username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <Input
                id="password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                className="absolute right-2 top-1/2 -translate-y-1/2"
                onClick={() => setShowPassword((s) => !s)}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </Button>
            </div>
            {error && (
              <p
                role="alert"
                className="text-xs"
                style={{ color: "hsl(var(--destructive))" }}
              >
                {error}
              </p>
            )}
          </div>
          <Button type="submit" disabled={!canSubmit} className="w-full">
            Sign in
          </Button>
          {ssoEnabled && (
            <>
              <div className="relative flex items-center gap-2">
                <Separator className="flex-1" />
                <span className="text-muted-foreground text-sm">or</span>
                <Separator className="flex-1" />
              </div>
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => {
                  window.location.href = "/api/auth/oidc/login";
                }}
              >
                Sign in with Authentik
              </Button>
            </>
          )}
        </form>
      </Card>
    </>
  );
}
