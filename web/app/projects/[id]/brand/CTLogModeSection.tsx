"use client";

/**
 * CTLogModeSection — CERT-03.
 *
 * Wrapper rendered by brand/page.tsx. Determines lead authority client-side
 * (mirrors SettingsTabContent authority computation) and renders CTLogModeCard
 * when the user has Lead+ authority.
 */

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";

import { listMemberships } from "@/app/projects/lib/api";
import { CTLogModeCard } from "./CTLogModeCard";

interface CTLogModeSectionProps {
  projectId: string;
  certstreamEnabled: boolean | null | undefined;
}

export function CTLogModeSection({
  projectId,
  certstreamEnabled,
}: CTLogModeSectionProps) {
  const { data: session } = useSession();
  const [isLead, setIsLead] = useState(false);

  const computeAuthority = useCallback(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const user = (session?.user as any) ?? null;
    // Dev-mode bypass: when AUTH_ENABLED=false there is no Auth.js session;
    // backend injects dev-stub Admin. Mirror that here.
    if (!user) {
      setIsLead(true);
      return;
    }
    if (user.role === "Admin") {
      setIsLead(true);
      return;
    }
    try {
      const memberships = await listMemberships(projectId);
      const lead = memberships.some(
        (m) => m.user_sub === user.sub && m.project_role === "Lead",
      );
      setIsLead(lead);
    } catch {
      setIsLead(false);
    }
  }, [session, projectId]);

  useEffect(() => {
    computeAuthority();
  }, [computeAuthority]);

  if (!isLead) return null;

  return (
    <div className="mt-6">
      <CTLogModeCard
        projectId={projectId}
        certstreamEnabled={certstreamEnabled}
        isLead={isLead}
      />
    </div>
  );
}
