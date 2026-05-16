"use client";

/**
 * /admin/yara-rules — Phase 27 YARA-01.
 * Admin CRUD for YARA rules: list, upload .yar content, toggle enabled, delete.
 * Access: Admin only (enforced server-side; page shows 403 toast on API error).
 */

import { useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  listYaraRules,
  createYaraRule,
  patchYaraRule,
  deleteYaraRule,
  type YaraRuleRead,
  type YaraRuleCreate,
} from "@/app/api-client";

export default function YaraRulesPage() {
  const [rules, setRules] = useState<YaraRuleRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<YaraRuleRead | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Upload form state
  const [form, setForm] = useState<YaraRuleCreate>({
    name: "",
    family: "",
    content: "",
    enabled: true,
  });

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setRules(await listYaraRules());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  async function handleCreate() {
    if (!form.name || !form.content) return;
    setSubmitting(true);
    try {
      await createYaraRule(form);
      setAddOpen(false);
      setForm({ name: "", family: "", content: "", enabled: true });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggle(rule: YaraRuleRead) {
    try {
      await patchYaraRule(rule.id, { enabled: !rule.enabled });
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setSubmitting(true);
    try {
      await deleteYaraRule(deleteTarget.id);
      setDeleteTarget(null);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">YARA Rules</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage YARA rules used to scan file samples and STIX patterns at ingest.
          </p>
        </div>
        <Dialog open={addOpen} onOpenChange={setAddOpen}>
          <DialogTrigger asChild>
            <Button size="sm">Upload Rule</Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Upload YARA Rule</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-1">
                <Label htmlFor="rule-name">Name *</Label>
                <Input
                  id="rule-name"
                  placeholder="e.g. Emotet_dropper"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="rule-family">Family</Label>
                <Input
                  id="rule-family"
                  placeholder="e.g. Emotet"
                  value={form.family}
                  onChange={(e) => setForm((f) => ({ ...f, family: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="rule-content">YARA Rule Content *</Label>
                <Textarea
                  id="rule-content"
                  placeholder={"rule Example {\n  strings:\n    $a = \"malware\"\n  condition:\n    $a\n}"}
                  className="font-mono text-xs h-40"
                  value={form.content}
                  onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
                />
                <p className="text-xs text-muted-foreground">
                  Paste .yar file contents. Rule is compiled immediately — invalid syntax returns an error.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  id="rule-enabled"
                  checked={form.enabled}
                  onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
                />
                <Label htmlFor="rule-enabled">Enabled immediately</Label>
              </div>
              {error && (
                <p className="text-sm text-red-600 rounded bg-red-50 p-2">{error}</p>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
              <Button onClick={handleCreate} disabled={submitting || !form.name || !form.content}>
                {submitting ? "Compiling..." : "Upload Rule"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {error && !addOpen && (
        <div className="rounded bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading rules...</p>
      ) : rules.length === 0 ? (
        <div className="rounded border border-dashed p-8 text-center text-sm text-muted-foreground">
          No YARA rules yet. Upload a .yar file to get started.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Family</TableHead>
              <TableHead>Scope</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rules.map((rule) => (
              <TableRow key={rule.id}>
                <TableCell className="font-medium font-mono text-sm">{rule.name}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {rule.family || "—"}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-xs">
                    {rule.project_id ? "Project" : "Global"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Switch
                    checked={rule.enabled}
                    onCheckedChange={() => handleToggle(rule)}
                    aria-label={`Toggle ${rule.name}`}
                  />
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {new Date(rule.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-red-600 hover:text-red-700 hover:bg-red-50"
                    onClick={() => setDeleteTarget(rule)}
                  >
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {/* Delete confirm dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete YARA Rule</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-2">
            Delete rule <span className="font-mono font-medium">{deleteTarget?.name}</span>?
            This also removes all match history for this rule. This cannot be undone.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={submitting}>
              {submitting ? "Deleting..." : "Delete Rule"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
