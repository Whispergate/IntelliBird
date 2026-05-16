"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { createCampaign, type CampaignRead } from "@/app/api-client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

interface CampaignDialogProps {
  actorId: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (campaign: CampaignRead) => void;
}

export function CampaignDialog({
  actorId,
  open,
  onOpenChange,
  onCreated,
}: CampaignDialogProps) {
  const [name, setName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [scope, setScope] = useState<"global" | "project">("global");
  const [summaryMd, setSummaryMd] = useState("");
  const [saving, setSaving] = useState(false);
  const [nameError, setNameError] = useState("");
  const [dateError, setDateError] = useState("");

  function resetForm() {
    setName("");
    setStartDate("");
    setEndDate("");
    setScope("global");
    setSummaryMd("");
    setNameError("");
    setDateError("");
  }

  function handleClose(v: boolean) {
    if (!v) resetForm();
    onOpenChange(v);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    let valid = true;
    if (!name.trim()) {
      setNameError("Campaign name is required.");
      valid = false;
    } else {
      setNameError("");
    }

    if (startDate && endDate && endDate < startDate) {
      setDateError("End date must be on or after start date.");
      valid = false;
    } else {
      setDateError("");
    }

    if (!valid) return;

    setSaving(true);
    try {
      const campaign = await createCampaign({
        name: name.trim(),
        actor_id: actorId,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        summary_md: summaryMd.trim() || undefined,
        project_id: scope === "global" ? undefined : undefined, // project scope requires project context
      });
      onCreated(campaign);
      resetForm();
      onOpenChange(false);
    } catch {
      setNameError("Failed to create campaign. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Create Campaign</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="campaign-name">Name *</Label>
            <Input
              id="campaign-name"
              placeholder="e.g. Operation Cozy Winter"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            {nameError && (
              <p className="text-destructive text-sm">{nameError}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor="campaign-start">Start Date</Label>
              <Input
                id="campaign-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="campaign-end">End Date</Label>
              <Input
                id="campaign-end"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>
          {dateError && (
            <p className="text-destructive text-sm -mt-2">{dateError}</p>
          )}

          <div className="flex flex-col gap-1">
            <Label htmlFor="campaign-scope">Scope</Label>
            <Select
              value={scope}
              onValueChange={(v) => setScope(v as "global" | "project")}
            >
              <SelectTrigger id="campaign-scope">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="global">Global campaign</SelectItem>
                <SelectItem value="project">This project only</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1">
            <Label htmlFor="campaign-summary">Summary</Label>
            <Textarea
              id="campaign-summary"
              placeholder="Brief campaign description…"
              value={summaryMd}
              onChange={(e) => setSummaryMd(e.target.value)}
              style={{ minHeight: 80 }}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => handleClose(false)}
            >
              Discard
            </Button>
            <Button
              type="submit"
              disabled={saving || !name.trim()}
              className="bg-teal-600 hover:bg-teal-500 text-white"
            >
              {saving ? <Loader2 className="animate-spin h-4 w-4 mr-2" /> : null}
              Create Campaign
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
