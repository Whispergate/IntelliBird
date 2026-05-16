"use client";

import { useEffect, useState } from "react";
import { getCibClusters } from "@/app/api-client";

/**
 * Minimal cluster shape used for rendering. Matches the subset of CibCluster
 * that the widget actually displays. This allows test mocks to pass lightweight
 * objects without satisfying the full CibCluster interface.
 */
interface ClusterDisplay {
  id: string;
  detected_at: string;
  member_count: number;
  severity: "medium" | "high";
}

interface Props {
  /**
   * When provided, the widget self-fetches CIB clusters for this project.
   * Omit (or leave undefined) to pass clusters directly via the `clusters` prop.
   */
  projectId?: string;
  /**
   * Number of social_listening sources for the project (or across all projects
   * when no projectId is provided). When 0, the widget renders nothing.
   */
  socialSourceCount: number;
  /**
   * Pre-fetched clusters to render. When provided, the widget does NOT
   * self-fetch from the API. Used by tests and by SSR-parent components.
   * When undefined and projectId is set, clusters are fetched client-side.
   */
  clusters?: ClusterDisplay[];
}

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function InfluenceOpsWidget({
  projectId,
  socialSourceCount,
  clusters: clustersProp,
}: Props) {
  // When clusters are provided as a prop (tests / SSR), skip internal fetch.
  const [clusters, setClusters] = useState<ClusterDisplay[]>(clustersProp ?? []);
  const [loading, setLoading] = useState(clustersProp === undefined && socialSourceCount > 0);

  useEffect(() => {
    // Only self-fetch when no clusters prop was provided and we have a projectId
    if (clustersProp !== undefined) return;
    if (socialSourceCount === 0 || !projectId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    getCibClusters(projectId, 5)
      .then((res) => {
        if (!cancelled) setClusters(res.clusters);
      })
      .catch(() => {
        if (!cancelled) setClusters([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, socialSourceCount, clustersProp]);

  if (socialSourceCount === 0) return null;

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <h3 className="text-sm font-semibold tracking-tight">Influence Operations</h3>
      {loading ? (
        <p className="text-muted-foreground text-sm">Loading...</p>
      ) : clusters.length === 0 ? (
        <p className="text-muted-foreground text-sm">No clusters detected recently.</p>
      ) : (
        <ul className="space-y-2">
          {clusters.map((cluster) => (
            <li key={cluster.id} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground text-xs font-mono">{cluster.id}</span>
              <span className="text-muted-foreground">{relativeTime(cluster.detected_at)}</span>
              <span>{cluster.member_count} accounts</span>
              <span
                className={
                  cluster.severity === "high"
                    ? "text-red-500 font-medium"
                    : "text-yellow-500 font-medium"
                }
              >
                {cluster.severity.toUpperCase()}
              </span>
            </li>
          ))}
        </ul>
      )}
      {projectId && (
        <a
          href={`/projects/${projectId}/timeline?filter=cib-cluster`}
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          View all in Timeline
        </a>
      )}
    </div>
  );
}
