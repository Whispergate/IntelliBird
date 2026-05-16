"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { useSession } from "next-auth/react";

import { type CampaignRead } from "@/app/api-client";
import { CampaignScopeBadge } from "@/app/actors/badges";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface CampaignCardProps {
  campaign: CampaignRead;
  onUnlink?: () => void;
}

function formatDateRange(start: string | null, end: string | null): string {
  if (!start && !end) return "Ongoing";
  const fmt = (d: string) =>
    new Date(d).toLocaleDateString("en-US", {
      month: "2-digit",
      day: "2-digit",
      year: "numeric",
    });
  if (start && end) return `${fmt(start)} – ${fmt(end)}`;
  if (start) return `${fmt(start)} – Present`;
  if (end) return `Until ${fmt(end)}`;
  return "Ongoing";
}

export function CampaignCard({ campaign, onUnlink }: CampaignCardProps) {
  const { data: session } = useSession();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const user = (session?.user as any) ?? null;
  const isLead =
    user?.role === "lead" ||
    user?.role === "admin" ||
    user?.role === "Lead" ||
    user?.role === "Admin";

  const [unlinkOpen, setUnlinkOpen] = useState(false);

  return (
    <TooltipProvider>
      <Card className="bg-card">
        <CardContent className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-col gap-2 flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-sm">{campaign.name}</span>
                <CampaignScopeBadge projectId={campaign.project_id} />
              </div>
              <span className="text-[12px] text-muted-foreground font-mono">
                {formatDateRange(campaign.start_date, campaign.end_date)}
              </span>
              {campaign.summary_md && (
                <p className="text-sm text-muted-foreground line-clamp-2">
                  {campaign.summary_md}
                </p>
              )}
            </div>

            {isLead && onUnlink && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0 text-muted-foreground hover:text-destructive"
                    aria-label="Unlink campaign"
                    onClick={() => setUnlinkOpen(true)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Unlink campaign</TooltipContent>
              </Tooltip>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Unlink confirmation dialog */}
      <Dialog open={unlinkOpen} onOpenChange={setUnlinkOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Unlink campaign?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This removes the link between{" "}
            <span className="font-medium text-foreground">{campaign.name}</span> and
            this actor. The campaign itself is not deleted.
          </p>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setUnlinkOpen(false)}
            >
              Keep link
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                setUnlinkOpen(false);
                onUnlink?.();
              }}
            >
              Unlink
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
}
