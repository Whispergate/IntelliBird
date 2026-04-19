"use client";

import { useState, useEffect } from "react";
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

type AdminUser = {
  id: string;
  username: string;
  role: "Admin" | "Analyst" | "Viewer";
  dashboard_roles: string[];
  enabled: boolean;
  must_change_password: boolean;
  locked: boolean;
  last_login_at: string | null;
  created_at: string;
};

type Props = {
  user: AdminUser;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onSaved: () => void;
};

export function EditUserDialog({ user, open, onOpenChange, onSaved }: Props) {
  const [role, setRole] = useState<"Admin" | "Analyst" | "Viewer">(user.role);
  const [dashboardRed, setDashboardRed] = useState(
    user.dashboard_roles.includes("red"),
  );
  const [dashboardBlue, setDashboardBlue] = useState(
    user.dashboard_roles.includes("blue"),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Reset state when user prop changes (new user opened)
  useEffect(() => {
    setRole(user.role);
    setDashboardRed(user.dashboard_roles.includes("red"));
    setDashboardBlue(user.dashboard_roles.includes("blue"));
    setError("");
  }, [user]);

  const isAdmin = role === "Admin";
  const effectiveRed = isAdmin ? true : dashboardRed;
  const effectiveBlue = isAdmin ? true : dashboardBlue;
  const dashboardValid = isAdmin || effectiveRed || effectiveBlue;
  const canSubmit = dashboardValid && !submitting;

  async function handleSubmit() {
    setSubmitting(true);
    setError("");
    try {
      const dashboard_roles: string[] = [];
      if (effectiveRed) dashboard_roles.push("red");
      if (effectiveBlue) dashboard_roles.push("blue");

      const res = await fetch(`/api/admin/users/${user.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role, dashboard_roles }),
      });

      if (!res.ok) {
        setError("An error occurred. Please try again.");
        return;
      }

      onOpenChange(false);
      onSaved();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Edit user</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {/* Username — read-only */}
          <div className="flex flex-col gap-2">
            <Label htmlFor="edit-username">Username</Label>
            <Input
              id="edit-username"
              value={user.username}
              readOnly
              disabled
              className="opacity-60"
            />
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
                  id="edit-dashboard-red"
                />
                Red
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={effectiveBlue}
                  onCheckedChange={(v) => !isAdmin && setDashboardBlue(Boolean(v))}
                  disabled={isAdmin}
                  id="edit-dashboard-blue"
                />
                Blue
              </label>
            </div>
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
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
