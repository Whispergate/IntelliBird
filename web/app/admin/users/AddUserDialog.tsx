"use client";

import { useState } from "react";
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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Props = {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onCreated: () => void;
};

export function AddUserDialog({ open, onOpenChange, onCreated }: Props) {
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<"Admin" | "Analyst" | "Viewer">("Viewer");
  const [dashboardRed, setDashboardRed] = useState(false);
  const [dashboardBlue, setDashboardBlue] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [usernameError, setUsernameError] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // When Admin role selected, auto-check + disable both dashboard checkboxes
  const isAdmin = role === "Admin";
  const effectiveRed = isAdmin ? true : dashboardRed;
  const effectiveBlue = isAdmin ? true : dashboardBlue;

  const passwordValid = password.length >= 12;
  const confirmValid = confirm === password && confirm.length > 0;
  const dashboardValid = isAdmin || effectiveRed || effectiveBlue;
  const canSubmit =
    username.trim().length > 0 &&
    passwordValid &&
    confirmValid &&
    dashboardValid &&
    !submitting;

  function resetForm() {
    setUsername("");
    setRole("Viewer");
    setDashboardRed(false);
    setDashboardBlue(false);
    setPassword("");
    setConfirm("");
    setShowPassword(false);
    setShowConfirm(false);
    setUsernameError("");
    setPasswordError("");
    setConfirmError("");
  }

  function handleOpenChange(o: boolean) {
    if (!o) resetForm();
    onOpenChange(o);
  }

  async function handleSubmit() {
    // Client-side validation
    let hasError = false;
    if (!username.trim()) {
      setUsernameError("Username is required.");
      hasError = true;
    } else {
      setUsernameError("");
    }
    if (!passwordValid) {
      setPasswordError("Password must be at least 12 characters.");
      hasError = true;
    } else {
      setPasswordError("");
    }
    if (!confirmValid) {
      setConfirmError("Passwords do not match.");
      hasError = true;
    } else {
      setConfirmError("");
    }
    if (hasError) return;

    setSubmitting(true);
    try {
      const dashboard_roles: string[] = [];
      if (effectiveRed) dashboard_roles.push("red");
      if (effectiveBlue) dashboard_roles.push("blue");

      const res = await fetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.trim(),
          role,
          dashboard_roles,
          initial_password: password,
        }),
      });

      if (res.status === 409) {
        setUsernameError("Username already exists.");
        return;
      }
      if (!res.ok) {
        setUsernameError("An error occurred. Please try again.");
        return;
      }

      resetForm();
      onOpenChange(false);
      onCreated();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add user</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {/* Username */}
          <div className="flex flex-col gap-2">
            <Label htmlFor="add-username">Username</Label>
            <Input
              id="add-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
              autoFocus
            />
            {usernameError && (
              <p className="text-xs text-destructive" role="alert">
                {usernameError}
              </p>
            )}
          </div>

          {/* Role */}
          <div className="flex flex-col gap-2">
            <Label>Role</Label>
            <Select
              value={role}
              onValueChange={(v) => setRole(v as "Admin" | "Analyst" | "Viewer")}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Admin">Admin</SelectItem>
                <SelectItem value="Analyst">Analyst</SelectItem>
                <SelectItem value="Viewer">Viewer</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Dashboard access */}
          <div className="flex flex-col gap-2">
            <Label>Dashboard access</Label>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={effectiveRed}
                  onCheckedChange={(v) => !isAdmin && setDashboardRed(Boolean(v))}
                  disabled={isAdmin}
                  id="add-dashboard-red"
                />
                Red
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={effectiveBlue}
                  onCheckedChange={(v) => !isAdmin && setDashboardBlue(Boolean(v))}
                  disabled={isAdmin}
                  id="add-dashboard-blue"
                />
                Blue
              </label>
            </div>
          </div>

          {/* Initial password */}
          <div className="flex flex-col gap-2">
            <Label htmlFor="add-password">Initial password</Label>
            <div className="relative">
              <Input
                id="add-password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                className="pr-10"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7"
                onClick={() => setShowPassword((p) => !p)}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </Button>
            </div>
            <p
              className="text-xs brand-mono"
              style={{
                color: passwordValid
                  ? "var(--brand-primary)"
                  : "var(--muted-foreground)",
              }}
            >
              {password.length} / 12 characters
            </p>
            {passwordError && (
              <p className="text-xs text-destructive" role="alert">
                {passwordError}
              </p>
            )}
          </div>

          {/* Confirm password */}
          <div className="flex flex-col gap-2">
            <Label htmlFor="add-confirm">Confirm password</Label>
            <div className="relative">
              <Input
                id="add-confirm"
                type={showConfirm ? "text" : "password"}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                className="pr-10"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={showConfirm ? "Hide password" : "Show password"}
                aria-pressed={showConfirm}
                className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7"
                onClick={() => setShowConfirm((p) => !p)}
              >
                {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
              </Button>
            </div>
            {confirmError && (
              <p className="text-xs text-destructive" role="alert">
                {confirmError}
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={submitting}
          >
            Discard user
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            Create user
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
