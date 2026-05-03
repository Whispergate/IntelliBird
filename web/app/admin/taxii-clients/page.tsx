'use client';

import { useEffect, useState } from 'react';
import {
  TaxiiClientRead,
  TaxiiClientCreated,
  listTaxiiClients,
  createTaxiiClient,
  revokeTaxiiClient,
} from '@/app/api-client';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

const TLP_LEVELS = ['white', 'clear', 'green', 'amber', 'amber+strict', 'red'];

function tlpBadgeVariant(level: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (level === 'red' || level === 'amber+strict') return 'destructive';
  if (level === 'amber') return 'secondary';
  return 'outline';
}

export default function TaxiiClientsPage() {
  const [clients, setClients] = useState<TaxiiClientRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [createdKey, setCreatedKey] = useState<TaxiiClientCreated | null>(null);
  const [keyShownOpen, setKeyShownOpen] = useState(false);

  // Create form state
  const [label, setLabel] = useState('');
  const [projectId, setProjectId] = useState('');
  const [tlpLevel, setTlpLevel] = useState('green');
  const [rpmLimit, setRpmLimit] = useState(60);
  const [creating, setCreating] = useState(false);

  const refresh = async () => {
    try {
      const list = await listTaxiiClients();
      setClients(list);
    } catch {
      // silently ignore — admin may not have clients yet
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const handleCreate = async () => {
    if (!label || !projectId) return;
    setCreating(true);
    try {
      const created = await createTaxiiClient({
        label,
        project_id: projectId,
        tlp_max_level: tlpLevel,
        rate_limit_rpm: rpmLimit,
      });
      setCreatedKey(created);
      setCreateOpen(false);
      setKeyShownOpen(true);
      setLabel('');
      setProjectId('');
      await refresh();
    } catch (e: unknown) {
      alert(`Failed to create partner key: ${e}`);
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id: string, lbl: string) => {
    if (!confirm(`Revoke partner key "${lbl}"? This takes effect immediately.`)) return;
    try {
      await revokeTaxiiClient(id);
      await refresh();
    } catch (e: unknown) {
      alert(`Failed to revoke: ${e}`);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">TAXII Partner Keys</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Manage external partner API keys for the TAXII 2.1 outbound server.
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>Issue New Key</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Issue TAXII Partner Key</DialogTitle>
              <DialogDescription>
                The raw API key will be shown once after creation. Copy it immediately.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <div>
                <Label htmlFor="partner-label">Partner Label</Label>
                <Input
                  id="partner-label"
                  placeholder="e.g. ACME Security Operations"
                  value={label}
                  onChange={e => setLabel(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="project-id">Project ID (UUID)</Label>
                <Input
                  id="project-id"
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  value={projectId}
                  onChange={e => setProjectId(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="tlp-level">Max TLP Level</Label>
                <Select value={tlpLevel} onValueChange={setTlpLevel}>
                  <SelectTrigger id="tlp-level">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TLP_LEVELS.map(l => (
                      <SelectItem key={l} value={l}>{l}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="rpm">Rate Limit (req/min)</Label>
                <Input
                  id="rpm"
                  type="number"
                  min={1}
                  max={600}
                  value={rpmLimit}
                  onChange={e => setRpmLimit(Number(e.target.value))}
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
              <Button onClick={handleCreate} disabled={creating || !label || !projectId}>
                {creating ? 'Issuing...' : 'Issue Key'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Raw key one-time display */}
      <Dialog open={keyShownOpen} onOpenChange={setKeyShownOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Copy Your API Key</DialogTitle>
            <DialogDescription>
              This key will not be shown again. Copy it now and share it securely with your partner.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md bg-muted p-3 font-mono text-sm break-all select-all">
            {createdKey?.raw_api_key}
          </div>
          <DialogFooter>
            <Button
              onClick={() => {
                if (createdKey?.raw_api_key) {
                  navigator.clipboard.writeText(createdKey.raw_api_key);
                }
              }}
            >
              Copy to Clipboard
            </Button>
            <Button variant="outline" onClick={() => setKeyShownOpen(false)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading partner keys...</p>
      ) : clients.length === 0 ? (
        <p className="text-muted-foreground text-sm">No partner keys issued yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Label</TableHead>
              <TableHead>Project ID</TableHead>
              <TableHead>Max TLP</TableHead>
              <TableHead>Rate Limit</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {clients.map(c => (
              <TableRow key={c.id} className={c.revoked ? 'opacity-50' : ''}>
                <TableCell className="font-medium">{c.label}</TableCell>
                <TableCell className="font-mono text-xs">{c.project_id.substring(0, 8)}...</TableCell>
                <TableCell>
                  <Badge variant={tlpBadgeVariant(c.tlp_max_level)}>
                    TLP:{c.tlp_max_level.toUpperCase()}
                  </Badge>
                </TableCell>
                <TableCell>{c.rate_limit_rpm} rpm</TableCell>
                <TableCell>
                  {c.revoked ? (
                    <Badge variant="destructive">Revoked</Badge>
                  ) : (
                    <Badge variant="outline" className="text-green-600 border-green-600">Active</Badge>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {new Date(c.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  {!c.revoked && (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => handleRevoke(c.id, c.label)}
                    >
                      Revoke
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
