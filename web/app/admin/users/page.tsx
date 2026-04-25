"use client";

import { useState, useEffect, useCallback } from "react";
import { Pencil, LockOpen, UserX, UserCheck, KeyRound, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AddUserDialog } from "./AddUserDialog";
import { EditUserDialog } from "./EditUserDialog";
import { ConfirmDialog } from "./ConfirmDialog";
import { ResetPasswordDialog } from "./ResetPasswordDialog";

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

const ROLE_BADGE_STYLES: Record<string, React.CSSProperties> = {
  Admin: {
    background: "rgba(29,158,117,0.15)",
    border: "1px solid #1D9E75",
    color: "#1D9E75",
  },
  Analyst: {
    background: "rgba(159,225,203,0.20)",
    border: "1px solid #9FE1CB",
    color: "#9FE1CB",
  },
  Viewer: {
    background: "rgba(136,135,128,0.15)",
    border: "1px solid #888780",
    color: "#888780",
  },
};

const DASHBOARD_BADGE_STYLES: Record<string, React.CSSProperties> = {
  red: {
    background: "rgba(220,38,38,0.15)",
    border: "1px solid hsl(var(--destructive))",
    color: "hsl(var(--destructive))",
  },
  blue: {
    background: "rgba(29,158,117,0.15)",
    border: "1px solid #1D9E75",
    color: "#1D9E75",
  },
};

function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className="brand-caption h-6 px-3 inline-flex items-center rounded"
      style={ROLE_BADGE_STYLES[role] ?? ROLE_BADGE_STYLES.Viewer}
    >
      {role}
    </span>
  );
}

function DashboardBadge({ dashboard }: { dashboard: string }) {
  return (
    <span
      className="brand-caption h-6 px-3 inline-flex items-center rounded"
      style={DASHBOARD_BADGE_STYLES[dashboard] ?? DASHBOARD_BADGE_STYLES.blue}
    >
      {dashboard === "red" ? "Red" : "Blue"}
    </span>
  );
}

function formatLastLogin(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AdminUser | null>(null);
  const [disableTarget, setDisableTarget] = useState<AdminUser | null>(null);
  const [enableTarget, setEnableTarget] = useState<AdminUser | null>(null);
  const [unlockTarget, setUnlockTarget] = useState<AdminUser | null>(null);
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch("/api/admin/users");
      if (r.ok) setUsers(await r.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // Fetch current user once so we can hide Delete on the operator's own row.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/auth/me");
        if (!r.ok) return;
        const me = await r.json();
        const id = typeof me?.id === "string" ? me.id : null;
        if (!cancelled) setCurrentUserId(id);
      } catch {
        // ignore — Delete button simply stays visible everywhere as a fallback;
        // backend still enforces cannot_delete_self.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <TooltipProvider>
      <div className="p-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="brand-heading">Users</h1>
          <Button onClick={() => setAddOpen(true)}>Add user</Button>
        </div>
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Username</TableHead>
                <TableHead style={{ width: 120 }}>Role</TableHead>
                <TableHead style={{ width: 140 }}>Dashboards</TableHead>
                <TableHead style={{ width: 100 }}>Status</TableHead>
                <TableHead style={{ width: 140 }}>Last login</TableHead>
                <TableHead style={{ width: 160 }} className="text-right">
                  Actions
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!loading && users.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-12">
                    <div className="flex flex-col gap-2">
                      <p style={{ color: "var(--muted-foreground)" }}>
                        No users
                      </p>
                      <p
                        className="text-xs"
                        style={{ color: "var(--muted-foreground)" }}
                      >
                        Create the first admin account via /setup.
                      </p>
                    </div>
                  </TableCell>
                </TableRow>
              )}
              {users.map((u) => (
                <TableRow
                  key={u.id}
                  className={!u.enabled ? "opacity-40 italic" : ""}
                  style={{ minHeight: 48 }}
                >
                  <TableCell>{u.username}</TableCell>
                  <TableCell>
                    <RoleBadge role={u.role} />
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {u.dashboard_roles.map((d) => (
                        <DashboardBadge key={d} dashboard={d} />
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    {u.locked ? (
                      <Badge
                        variant="outline"
                        style={{
                          color: "hsl(var(--destructive))",
                          borderColor: "hsl(var(--destructive))",
                        }}
                      >
                        Locked
                      </Badge>
                    ) : u.enabled ? (
                      <span style={{ color: "var(--brand-primary)" }}>
                        Active
                      </span>
                    ) : (
                      <span style={{ color: "var(--muted-foreground)" }}>
                        Disabled
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {formatLastLogin(u.last_login_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex gap-1 justify-end">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Edit user"
                            onClick={() => setEditTarget(u)}
                          >
                            <Pencil size={16} />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Edit user</TooltipContent>
                      </Tooltip>
                      {u.locked && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label="Unlock account"
                              onClick={() => setUnlockTarget(u)}
                            >
                              <LockOpen size={16} />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Unlock account</TooltipContent>
                        </Tooltip>
                      )}
                      {u.enabled ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label="Disable user"
                              onClick={() => setDisableTarget(u)}
                            >
                              <UserX size={16} />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Disable user</TooltipContent>
                        </Tooltip>
                      ) : (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label="Re-enable user"
                              onClick={() => setEnableTarget(u)}
                            >
                              <UserCheck size={16} />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Re-enable user</TooltipContent>
                        </Tooltip>
                      )}
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label="Reset password"
                            onClick={() => setResetTarget(u)}
                          >
                            <KeyRound size={16} />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Reset password</TooltipContent>
                      </Tooltip>
                      {u.id !== currentUserId && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label="Delete user"
                              onClick={() => setDeleteTarget(u)}
                              style={{ color: "hsl(var(--destructive))" }}
                            >
                              <Trash2 size={16} />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Delete user</TooltipContent>
                        </Tooltip>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>

        <AddUserDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          onCreated={reload}
        />
        {editTarget && (
          <EditUserDialog
            user={editTarget}
            open={true}
            onOpenChange={(o) => !o && setEditTarget(null)}
            onSaved={reload}
          />
        )}
        {disableTarget && (
          <ConfirmDialog
            open={true}
            title="Disable user"
            body={`Disable ${disableTarget.username}? They will be signed out of all active sessions immediately and cannot sign in until re-enabled.`}
            confirmLabel="Disable user"
            confirmVariant="destructive"
            dismissLabel="Keep active"
            onConfirm={async () => {
              await fetch(`/api/admin/users/${disableTarget.id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled: false }),
              });
              setDisableTarget(null);
              reload();
            }}
            onOpenChange={(o) => !o && setDisableTarget(null)}
          />
        )}
        {enableTarget && (
          <ConfirmDialog
            open={true}
            title="Re-enable user"
            body={`Re-enable ${enableTarget.username}? They will be able to sign in immediately.`}
            confirmLabel="Re-enable user"
            confirmVariant="default"
            dismissLabel="Keep disabled"
            onConfirm={async () => {
              await fetch(`/api/admin/users/${enableTarget.id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled: true }),
              });
              setEnableTarget(null);
              reload();
            }}
            onOpenChange={(o) => !o && setEnableTarget(null)}
          />
        )}
        {unlockTarget && (
          <ConfirmDialog
            open={true}
            title="Unlock account"
            body={`Clear the failed-attempt counter for ${unlockTarget.username}? The user will be able to sign in immediately.`}
            confirmLabel="Unlock account"
            confirmVariant="default"
            dismissLabel="Keep locked"
            onConfirm={async () => {
              await fetch(`/api/admin/users/${unlockTarget.id}/unlock`, {
                method: "POST",
              });
              setUnlockTarget(null);
              reload();
            }}
            onOpenChange={(o) => !o && setUnlockTarget(null)}
          />
        )}
        <ResetPasswordDialog
          user={resetTarget}
          open={resetTarget !== null}
          onOpenChange={(o) => !o && setResetTarget(null)}
          onSuccess={reload}
        />
        {deleteTarget && (
          <ConfirmDialog
            open={true}
            title={`Delete ${deleteTarget.username}?`}
            body={`This permanently removes ${deleteTarget.username}. The account cannot be recovered, all outstanding sessions are invalidated, and the user will be signed out everywhere.`}
            confirmLabel="Delete user"
            confirmVariant="destructive"
            dismissLabel="Cancel"
            onConfirm={async () => {
              const target = deleteTarget;
              setDeleteTarget(null);
              const res = await fetch(`/api/admin/users/${target.id}`, {
                method: "DELETE",
              });
              if (!res.ok) {
                let detail = "";
                try {
                  const body = await res.json();
                  detail = typeof body?.detail === "string" ? body.detail : "";
                } catch {
                  // ignore
                }
                // Surface failure inline; mirrors existing Disable/Enable
                // handlers which currently rely on the list refresh to
                // signal outcome. Browser alert is intentionally minimal.
                if (typeof window !== "undefined") {
                  window.alert(
                    `Failed to delete user: ${res.statusText}${
                      detail ? ` (${detail})` : ""
                    }`,
                  );
                }
              }
              reload();
            }}
            onOpenChange={(o) => !o && setDeleteTarget(null)}
          />
        )}
      </div>
    </TooltipProvider>
  );
}
