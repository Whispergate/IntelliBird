"use client";

import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type QueuedJob = {
  message_id: string;
  actor_name: string | null;
  args: string[];
  enqueued_at: number | null;
};

type StreamingJob = {
  job_id: string;
  project_id: string | null;
  chunk_count: number;
  status: "running" | "done" | "cancelled";
};

type RerankLock = { project_id: string; ttl_seconds: number };

type AIJobsResponse = {
  queue_depth: number;
  queued: QueuedJob[];
  streaming: StreamingJob[];
  rerank_in_progress: RerankLock[];
  workers_alive: number;
  server_time_ms: number;
};

const REFRESH_MS = 5_000;

function ago(epochSeconds: number | null, nowMs: number): string {
  if (!epochSeconds) return "—";
  const sec = Math.max(0, Math.floor(nowMs / 1000 - epochSeconds));
  if (sec < 60) return `${sec}s ago`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

function statusBadge(status: StreamingJob["status"]) {
  if (status === "running") {
    return <Badge className="bg-blue-900/40 text-blue-300 border-blue-700">running</Badge>;
  }
  if (status === "done") {
    return <Badge className="bg-green-900/40 text-green-300 border-green-700">done</Badge>;
  }
  return <Badge className="bg-red-900/40 text-red-300 border-red-700">cancelled</Badge>;
}

export default function AIJobsPage() {
  const { data: session } = useSession();
  const role = (session?.user as { role?: string } | undefined)?.role;
  const isAdmin = !session || role === "Admin";

  const [data, setData] = useState<AIJobsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/ai-jobs", { cache: "no-store" });
      if (res.status === 403) {
        setError("forbidden");
        return;
      }
      if (!res.ok) {
        setError(`http_${res.status}`);
        return;
      }
      setData(await res.json());
      setError(null);
    } catch {
      setError("network");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  if (!isAdmin) {
    return (
      <div className="max-w-3xl mx-auto pt-6">
        <p className="text-muted-foreground">Admin only.</p>
      </div>
    );
  }

  if (error === "forbidden") {
    return (
      <div className="max-w-3xl mx-auto pt-6">
        <p className="text-muted-foreground">Forbidden.</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto pt-6 px-4 space-y-8">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="brand-heading text-foreground">AI Jobs</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Workers alive: {data?.workers_alive ?? "—"} · Queue depth:{" "}
            {data?.queue_depth ?? "—"} · Auto-refresh 5s
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          Refresh
        </Button>
      </div>

      {/* Queued */}
      <section>
        <h2 className="brand-subheading mb-3">Queued ({data?.queued.length ?? 0})</h2>
        {!data || data.queued.length === 0 ? (
          <p className="text-sm text-muted-foreground">No pending jobs.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Actor</TableHead>
                <TableHead>Args</TableHead>
                <TableHead>Enqueued</TableHead>
                <TableHead className="brand-mono text-xs">Message ID</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.queued.map((j) => (
                <TableRow key={j.message_id}>
                  <TableCell className="brand-mono text-xs">{j.actor_name ?? "—"}</TableCell>
                  <TableCell className="brand-mono text-xs">{j.args.join(", ")}</TableCell>
                  <TableCell>{ago(j.enqueued_at, data.server_time_ms)}</TableCell>
                  <TableCell className="brand-mono text-xs">{j.message_id.slice(0, 8)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      {/* Streaming */}
      <section>
        <h2 className="brand-subheading mb-3">
          Streaming jobs ({data?.streaming.length ?? 0})
        </h2>
        {!data || data.streaming.length === 0 ? (
          <p className="text-sm text-muted-foreground">No streaming jobs.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead>Job ID</TableHead>
                <TableHead>Project</TableHead>
                <TableHead className="text-right">Chunks</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.streaming.map((j) => (
                <TableRow key={j.job_id}>
                  <TableCell>{statusBadge(j.status)}</TableCell>
                  <TableCell className="brand-mono text-xs">{j.job_id.slice(0, 8)}</TableCell>
                  <TableCell className="brand-mono text-xs">
                    {j.project_id ? j.project_id.slice(0, 8) : "—"}
                  </TableCell>
                  <TableCell className="text-right brand-mono">{j.chunk_count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      {/* Rerank locks */}
      <section>
        <h2 className="brand-subheading mb-3">
          Rerank in progress ({data?.rerank_in_progress.length ?? 0})
        </h2>
        {!data || data.rerank_in_progress.length === 0 ? (
          <p className="text-sm text-muted-foreground">No active rerank locks.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead className="text-right">TTL</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rerank_in_progress.map((r) => (
                <TableRow key={r.project_id}>
                  <TableCell className="brand-mono text-xs">{r.project_id.slice(0, 8)}</TableCell>
                  <TableCell className="text-right brand-mono">{r.ttl_seconds}s</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      {error && error !== "forbidden" && (
        <p className="text-sm text-red-400">Could not load: {error}</p>
      )}
    </div>
  );
}
