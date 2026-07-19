"use client";
import { cn } from "@/lib/utils";

const ACTION_STYLES: Record<string, { bg: string; text: string }> = {
  create:  { bg: "bg-green-500/15",             text: "text-green-300" },
  update:  { bg: "bg-teal-900/40",              text: "text-teal-300" },
  delete:  { bg: "bg-destructive/15",           text: "text-red-400" },
  approve: { bg: "bg-[var(--brand-signal)]/15", text: "text-[var(--brand-signal)]" },
  reject:  { bg: "bg-muted",                    text: "text-muted-foreground" },
};

export function ActionBadge({ action }: { action: string }) {
  const style = ACTION_STYLES[action.toLowerCase()];
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-1 rounded-sm border text-[12px] font-medium uppercase tracking-wide",
        style?.bg ?? "bg-muted",
        style?.text ?? "text-muted-foreground"
      )}
    >
      {action}
    </span>
  );
}
