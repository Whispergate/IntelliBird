"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Eye, EyeOff } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

type SetupStatus = { setup_token_set: boolean; user_count: number };

export default function SetupPage() {
  const router = useRouter();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [username, setUsername] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [usernameError, setUsernameError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // /api/system/setup-status is pre-auth; exposes setup_token_set + user_count.
    fetch("/api/system/setup-status")
      .then((r) => r.json())
      .then((s: any) =>
        setStatus({
          setup_token_set: Boolean(s.setup_token_set),
          user_count: Number(s.user_count ?? 0),
        })
      )
      .catch(() => setStatus({ setup_token_set: false, user_count: 0 }));
  }, []);

  useEffect(() => {
    if (status && !status.setup_token_set) {
      router.replace("/");
    }
  }, [status, router]);

  if (status === null) return null;

  if (!status.setup_token_set) {
    return null;
  }

  if (status.user_count > 0) {
    return (
      <Card className="p-6">
        <h1 className="brand-heading mb-4">Setup already complete</h1>
        <p>
          An admin account already exists. Remove{" "}
          <code>SETUP_TOKEN</code> and restart the api service.
        </p>
      </Card>
    );
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setUsernameError(null);
    setPasswordError(null);
    setConfirmError(null);
    setTokenError(null);

    if (password.length < 12) {
      setPasswordError("Password must be at least 12 characters.");
      return;
    }
    if (password !== confirm) {
      setConfirmError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      // Operator pastes the SETUP_TOKEN into the form field so the UI can send
      // it as X-Setup-Token - self-contained path, no CLI workaround needed.
      if (setupToken.trim()) {
        headers["X-Setup-Token"] = setupToken.trim();
      }

      const res = await fetch("/api/admin/setup", {
        method: "POST",
        headers,
        body: JSON.stringify({ username, password }),
      });
      if (res.status === 403) {
        setTokenError(
          "Setup token is invalid or has expired. Check SETUP_TOKEN in the api environment."
        );
        return;
      }
      if (res.status === 409) {
        const body = await res.json().catch(() => ({}));
        if (body?.detail === "setup_already_complete") {
          router.replace("/login");
          return;
        }
        setUsernameError("Username already taken.");
        return;
      }
      if (res.status === 422) {
        setPasswordError("Password must be at least 12 characters.");
        return;
      }
      if (!res.ok) {
        setTokenError("Setup failed. See browser console and backend logs.");
        return;
      }
      toast.success("Admin account created", {
        description: "Sign in to continue.",
        duration: 4000,
      });
      router.push("/login");
    } finally {
      setSubmitting(false);
    }
  }

  const passwordCounterColor =
    password.length >= 12 ? "var(--brand-primary)" : "var(--muted-foreground)";

  return (
    <>
      <div className="flex justify-center mb-6">
        <img
          src="/brand/logo.svg"
          alt="IntelliBird"
          style={{ height: "96px", width: "auto", display: "block" }}
        />
      </div>
      <Card className="p-6">
        <h1 className="brand-heading mb-4">First-Admin Setup</h1>
        <p className="mb-6 text-sm">
          This page is visible because <code>SETUP_TOKEN</code> is set. Create the
          initial admin, then unset <code>SETUP_TOKEN</code> and restart the api service.
        </p>
      {tokenError && (
        <div
          role="alert"
          className="mb-4 p-3 rounded border"
          style={{
            borderColor: "hsl(var(--destructive))",
            color: "hsl(var(--destructive))",
          }}
        >
          {tokenError}
        </div>
      )}
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="setup-token">Setup token</Label>
          <Input
            id="setup-token"
            type="password"
            autoComplete="off"
            value={setupToken}
            onChange={(e) => setSetupToken(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="username">Username</Label>
          <Input
            id="username"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          {usernameError && (
            <p role="alert" className="text-xs" style={{ color: "hsl(var(--destructive))" }}>
              {usernameError}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="password">Password</Label>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
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
          <p className="brand-mono text-xs" style={{ color: passwordCounterColor }}>
            {password.length} / 12 characters
          </p>
          {passwordError && (
            <p role="alert" className="text-xs" style={{ color: "hsl(var(--destructive))" }}>
              {passwordError}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="confirm">Confirm password</Label>
          <div className="relative">
            <Input
              id="confirm"
              type={showConfirm ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={showConfirm ? "Hide password" : "Show password"}
              aria-pressed={showConfirm}
              className="absolute right-2 top-1/2 -translate-y-1/2"
              onClick={() => setShowConfirm((s) => !s)}
            >
              {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
            </Button>
          </div>
          {confirmError && (
            <p role="alert" className="text-xs" style={{ color: "hsl(var(--destructive))" }}>
              {confirmError}
            </p>
          )}
        </div>
        <Button
          type="submit"
          className="w-full"
          disabled={!username || password.length < 12 || submitting}
        >
          Create admin account
        </Button>
      </form>
      </Card>
    </>
  );
}
