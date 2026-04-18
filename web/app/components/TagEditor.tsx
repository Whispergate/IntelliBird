"use client";

import { useState, type KeyboardEvent } from "react";
import { toast } from "sonner";
import { patchEventTags } from "@/app/api-client";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const TAG_REGEX = /^[a-z0-9_-]{1,32}$/;
const TAG_ERROR =
  "Tags must be lowercase letters, numbers, hyphens, underscores (max 32 chars)";

const CHIP_STYLE = {
  backgroundColor: "rgba(159, 225, 203, 0.12)",
  color: "#9FE1CB",
  borderColor: "#0F6E56",
};

// Suggested tags grouped by intent — click to apply. Same vocabulary as
// Phase 5 widget queries (actor, c2, exploit, tooling, vendor-advisory,
// high-severity) so tagged events roll up into dashboard widgets.
const SUGGESTED_TAG_GROUPS: { label: string; tags: string[] }[] = [
  { label: "Severity", tags: ["critical", "high-severity", "medium-severity", "low-severity"] },
  { label: "Threat type", tags: ["apt", "actor", "malware", "ransomware", "phishing", "exploit", "vulnerability", "ioc"] },
  { label: "Kill chain", tags: ["recon", "initial-access", "persistence", "privilege-escalation", "c2", "exfiltration", "impact"] },
  { label: "Activity", tags: ["tooling", "offensive-tooling", "detection", "vendor-advisory"] },
];

const SUGGESTED_CHIP_STYLE = {
  backgroundColor: "transparent",
  color: "#888780",
  borderColor: "#0F6E56",
  borderStyle: "dashed" as const,
};

export function TagEditor({
  eventId,
  initialTags,
}: {
  eventId: string;
  initialTags: string[];
}) {
  const [tags, setTags] = useState<string[]>(initialTags);
  const [inputValue, setInputValue] = useState("");
  const [invalid, setInvalid] = useState(false);

  async function attemptAdd() {
    const trimmed = inputValue.trim().toLowerCase();
    if (!trimmed) return;
    if (!TAG_REGEX.test(trimmed)) {
      setInvalid(true);
      setTimeout(() => setInvalid(false), 400);
      return;
    }
    if (tags.includes(trimmed)) {
      setInputValue("");
      return;
    }
    const prev = tags;
    setTags([...tags, trimmed]);
    setInputValue("");
    try {
      await patchEventTags(eventId, { add: [trimmed], remove: [] });
    } catch {
      setTags(prev);
      toast.error("Failed to update tags. Reverted.");
    }
  }

  async function applySuggested(tag: string) {
    if (tags.includes(tag)) return;
    const prev = tags;
    setTags([...tags, tag]);
    try {
      await patchEventTags(eventId, { add: [tag], remove: [] });
    } catch {
      setTags(prev);
      toast.error("Failed to update tags. Reverted.");
    }
  }

  async function attemptRemove(tag: string) {
    const prev = tags;
    setTags(tags.filter((t) => t !== tag));
    try {
      await patchEventTags(eventId, { add: [], remove: [tag] });
    } catch {
      setTags(prev);
      toast.error("Failed to update tags. Reverted.");
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      attemptAdd();
    }
  }

  const appliedSet = new Set(tags);

  return (
    <div data-testid="tag-editor" className="flex flex-col gap-2">
      {/* Applied tags + freeform input */}
      <div
        className={`flex flex-wrap items-center gap-1 ${
          invalid ? "ring-1 ring-destructive rounded-md" : ""
        }`}
        title={invalid ? TAG_ERROR : undefined}
      >
      {tags.map((t) => (
        <Badge
          key={t}
          variant="outline"
          className="brand-caption inline-flex items-center gap-1"
          style={CHIP_STYLE}
          data-testid="tag-chip"
        >
          {t}
          <button
            type="button"
            onClick={() => attemptRemove(t)}
            aria-label={`Remove tag ${t}`}
            className="text-muted-foreground hover:text-destructive ml-1"
            data-testid={`remove-${t}`}
          >
            &times;
          </button>
        </Badge>
      ))}
      <Input
        type="text"
        placeholder="add tag..."
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={attemptAdd}
        className="h-6 text-xs border-none bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0"
        style={{ width: "10ch", padding: "0 4px" }}
        data-testid="tag-input"
        aria-label="Add tag"
        aria-invalid={invalid || undefined}
      />
      </div>

      {/* Suggested tags — grouped, click to apply, hide if already applied */}
      <div className="flex flex-col gap-1" data-testid="tag-suggestions">
        {SUGGESTED_TAG_GROUPS.map((group) => {
          const available = group.tags.filter((t) => !appliedSet.has(t));
          if (available.length === 0) return null;
          return (
            <div key={group.label} className="flex flex-wrap items-center gap-1">
              <span
                className="brand-caption text-[10px] mr-1 text-muted-foreground"
                style={{ letterSpacing: "0.12em" }}
              >
                {group.label}
              </span>
              {available.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => applySuggested(t)}
                  data-testid={`suggested-${t}`}
                  aria-label={`Apply suggested tag ${t}`}
                  className="brand-caption inline-flex items-center rounded-md border px-2 py-0.5 hover:opacity-80 cursor-pointer"
                  style={SUGGESTED_CHIP_STYLE}
                >
                  +{t}
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
