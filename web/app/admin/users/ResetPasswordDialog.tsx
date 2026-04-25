"use client";

import { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  user: { id: string; username: string } | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onSuccess: () => void;
};

export function ResetPasswordDialog({
  user,
  open,
  onOpenChange,
  onSuccess,
}: Props) {
  const [pw, setPw] = useState("");
  const [show, setShow] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Reset state whenever dialog re-opens or target changes
  useEffect(() => {
    if (open) {
      setPw("");
      setShow(false);
      setError("");
      setSubmitting(false);
    }
  }, [open, user?.id]);

  const canSubmit = !submitting && pw.length >= 12;

  async function handleSubmit() {
    if (!user) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch(`/api/admin/users/${user.id}/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: pw }),
      });

      if (res.ok) {
        onOpenChange(false);
        onSuccess();
        return;
      }

      if (res.status === 422) {
        setError("Password must be at least 12 characters.");
        return;
      }

      let detail = "";
      try {
        const body = await res.json();
        detail = typeof body?.detail === "string" ? body.detail : "";
      } catch {
        // ignore parse errors
      }

      if (res.status === 400 && detail === "oidc_only_user") {
        setError(
          "This user signs in via SSO; reset their password in Authentik.",
        );
        return;
      }

      setError(detail ? `Error: ${detail}` : "An error occurred. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            Reset password{user ? ` for ${user.username}` : ""}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="reset-password-input">New password</Label>
            <div className="flex gap-2">
              <Input
                id="reset-password-input"
                type={show ? "text" : "password"}
                value={pw}
                onChange={(e) => setPw(e.target.value)}
                minLength={12}
                autoComplete="new-password"
                placeholder="At least 12 characters"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label={show ? "Hide password" : "Show password"}
                onClick={() => setShow((s) => !s)}
              >
                {show ? <EyeOff size={16} /> : <Eye size={16} />}
              </Button>
            </div>
            <p
              className="text-xs"
              style={{ color: "var(--muted-foreground)" }}
            >
              User will be forced to change this on next login.
            </p>
          </div>

          {error && (
            <p className="text-xs text-destructive" role="alert">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            Reset password
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
