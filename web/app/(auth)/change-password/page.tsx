"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Eye, EyeOff } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

export default function ChangePasswordPage() {
  return (
    <Suspense fallback={null}>
      <ChangePasswordPageInner />
    </Suspense>
  );
}

function ChangePasswordPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const reason = searchParams.get("reason");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [currentError, setCurrentError] = useState<string | null>(null);
  const [newPasswordError, setNewPasswordError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const newPasswordCounterColor =
    newPassword.length >= 12 ? "var(--brand-primary)" : "var(--muted-foreground)";

  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length >= 12 &&
    confirmPassword.length > 0 &&
    !submitting;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setCurrentError(null);
    setNewPasswordError(null);
    setConfirmError(null);

    if (newPassword.length < 12) {
      setNewPasswordError("Password must be at least 12 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setConfirmError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      if (res.status === 401) {
        setCurrentError("Incorrect password.");
        return;
      }
      if (res.status === 400) {
        const body = await res.json().catch(() => ({}));
        if (body?.detail === "new_password_same_as_current") {
          setNewPasswordError("New password must differ from your current password.");
          return;
        }
      }
      if (res.status === 422) {
        setNewPasswordError("Password must be at least 12 characters.");
        return;
      }
      if (!res.ok) {
        setNewPasswordError("Password update failed.");
        return;
      }
      toast.success("Password updated", { duration: 3000 });
      // Post-success: determine landing from /api/auth/me dashboard_roles claim.
      const me = await fetch("/api/auth/me")
        .then((r) => r.json())
        .catch(() => ({}));
      const next = searchParams.get("next");
      if (next) {
        router.push(next);
      } else if (Array.isArray(me.dashboard_roles) && me.dashboard_roles.includes("red")) {
        router.push("/red");
      } else if (Array.isArray(me.dashboard_roles) && me.dashboard_roles.includes("blue")) {
        router.push("/blue");
      } else {
        router.push("/");
      }
    } finally {
      setSubmitting(false);
    }
  }

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
        <h2 className="brand-heading mb-4">
          {reason === "first_login"
            ? "Change your password"
            : "Change your password"}
        </h2>
        <p className="mb-6 text-sm">
          {reason === "first_login"
            ? "You must set a new password before continuing. Your initial password was set by an admin."
            : "Change your password."}
        </p>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="current-password">Current password</Label>
            <div className="relative">
              <Input
                id="current-password"
                type={showCurrent ? "text" : "password"}
                autoComplete="current-password"
                autoFocus
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={showCurrent ? "Hide password" : "Show password"}
                aria-pressed={showCurrent}
                className="absolute right-2 top-1/2 -translate-y-1/2"
                onClick={() => setShowCurrent((s) => !s)}
              >
                {showCurrent ? <EyeOff size={16} /> : <Eye size={16} />}
              </Button>
            </div>
            {currentError && (
              <p role="alert" className="text-xs" style={{ color: "hsl(var(--destructive))" }}>
                {currentError}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-password">New password</Label>
            <div className="relative">
              <Input
                id="new-password"
                type={showNew ? "text" : "password"}
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={showNew ? "Hide password" : "Show password"}
                aria-pressed={showNew}
                className="absolute right-2 top-1/2 -translate-y-1/2"
                onClick={() => setShowNew((s) => !s)}
              >
                {showNew ? <EyeOff size={16} /> : <Eye size={16} />}
              </Button>
            </div>
            <p className="brand-mono text-xs" style={{ color: newPasswordCounterColor }}>
              {newPassword.length} / 12 characters
            </p>
            {newPasswordError && (
              <p role="alert" className="text-xs" style={{ color: "hsl(var(--destructive))" }}>
                {newPasswordError}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="confirm-password">Confirm new password</Label>
            <div className="relative">
              <Input
                id="confirm-password"
                type={showConfirm ? "text" : "password"}
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
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
          <Button type="submit" disabled={!canSubmit} className="w-full">
            Update password
          </Button>
        </form>
      </Card>
    </>
  );
}
