"use client";

/**
 * /admin/sigma-rules — Phase 29 SIGMA-03.
 * Admin CRUD for Sigma rules: list, add rule YAML, toggle enabled, delete.
 * Includes Test button that shows match count against recent events.
 * Access: Admin only (enforced server-side; page shows error on API error).
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  listSigmaRules,
  createSigmaRule,
  patchSigmaRule,
  deleteSigmaRule,
  testSigmaRule,
  type SigmaRuleRead,
  type SigmaRuleCreate,
} from "@/app/api-client";

export default function SigmaRulesPage() {
  const [rules, setRules] = useState<SigmaRuleRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SigmaRuleRead | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Add form state
  const [form, setForm] = useState<SigmaRuleCreate>({
    name: "",
    content: "",
    level: null,
    enabled: true,
  });

  // Test state
  const [testResult, setTestResult] = useState<{ match_count: number } | null>(null);
  const [testing, setTesting] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setRules(await listSigmaRules());
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
      await createSigmaRule(form);
      setAddOpen(false);
      setForm({ name: "", content: "", level: null, enabled: true });
      setTestResult(null);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleToggle(rule: SigmaRuleRead) {
    try {
      await patchSigmaRule(rule.id, { enabled: !rule.enabled });
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setSubmitting(true);
    try {
      await deleteSigmaRule(deleteTarget.id);
      setDeleteTarget(null);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleTest() {
    if (!form.content) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testSigmaRule({ rule_yaml: form.content, project_id: form.project_id ?? null });
      setTestResult(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Sigma Rules</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage Sigma rules for automated event tagging at ingest.
          </p>
        </div>
        <Dialog open={addOpen} onOpenChange={(o) => { setAddOpen(o); if (!o) { setTestResult(null); setError(null); } }}>
          <DialogTrigger asChild>
            <Button size="sm">Add Rule</Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Add Sigma Rule</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-1">
                <Label htmlFor="rule-name">Name *</Label>
                <Input
                  id="rule-name"
                  placeholder="e.g. Suspicious_PowerShell"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="rule-level">Level</Label>
                <Select
                  value={form.level ?? ""}
                  onValueChange={(v) => setForm((f) => ({ ...f, level: v || null }))}
                >
                  <SelectTrigger id="rule-level">
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">None</SelectItem>
                    <SelectItem value="informational">informational</SelectItem>
                    <SelectItem value="low">low</SelectItem>
                    <SelectItem value="medium">medium</SelectItem>
                    <SelectItem value="high">high</SelectItem>
                    <SelectItem value="critical">critical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="rule-content">Sigma YAML *</Label>
                <Textarea
                  id="rule-content"
                  placeholder={"title: Example Rule\nstatus: experimental\ndetection:\n  selection:\n    description|contains: malware\n  condition: selection\nlevel: medium"}
                  className="font-mono text-xs h-40"
                  value={form.content}
                  onChange={(e) => { setForm((f) => ({ ...f, content: e.target.value })); setTestResult(null); }}
                />
                <p className="text-xs text-muted-foreground">
                  Parsed immediately — invalid YAML returns an error.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleTest}
                  disabled={testing || !form.content}
                >
                  {testing ? "Testing..." : "Test"}
                </Button>
                {testResult !== null && (
                  <Badge variant="secondary" className="text-xs">
                    {testResult.match_count} / 100 events matched
                  </Badge>
                )}
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
                {submitting ? "Saving..." : "Add Rule"}
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
          No Sigma rules yet. Add a rule to get started.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Level</TableHead>
              <TableHead>Tags</TableHead>
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
                <TableCell>
                  {rule.level ? (
                    <Badge variant="outline" className="text-xs">{rule.level}</Badge>
                  ) : "—"}
                </TableCell>
                <TableCell>
                  {(rule.tags ?? []).length > 0 ? (
                    rule.tags.slice(0, 3).map((t) => (
                      <Badge key={t} variant="secondary" className="text-xs mr-1">{t}</Badge>
                    ))
                  ) : "—"}
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
            <DialogTitle>Delete Sigma Rule</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-2">
            Delete rule <span className="font-mono font-medium">{deleteTarget?.name}</span>?
            This cannot be undone.
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
