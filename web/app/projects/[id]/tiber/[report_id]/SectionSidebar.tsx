"use client";

/**
 * SectionSidebar — left 240px nav for TIBER report editor.
 * UI-SPEC §2b.
 *
 * Six section items in fixed ECB order with CompletionBadge per item.
 * Active section: border-l-2 border-[var(--brand-signal)] bg-background/80.
 */

import { CompletionBadge, type CompletionState } from "../components/CompletionBadge";

export type SectionKey =
  | "scope"
  | "actionable_intelligence"
  | "threat_landscape"
  | "actor_profiles"
  | "threat_scenarios"
  | "scenario_x";

interface SectionDef {
  key: SectionKey;
  label: string;
}

const SECTIONS: SectionDef[] = [
  { key: "scope", label: "Scope of Intelligence Research" },
  { key: "actionable_intelligence", label: "Actionable Intelligence Assessment" },
  { key: "threat_landscape", label: "Threat Landscape" },
  { key: "actor_profiles", label: "Threat Actor Profiles" },
  { key: "threat_scenarios", label: "Threat Scenarios" },
  { key: "scenario_x", label: "Scenario X" },
];

interface SectionSidebarProps {
  activeSection: SectionKey;
  onSectionChange: (key: SectionKey) => void;
  /** Map of section key → completion state */
  completionStates: Record<SectionKey, CompletionState>;
  /** Map of section key → missing field names (for tooltip) */
  missingFields: Record<SectionKey, string[]>;
}

export function SectionSidebar({
  activeSection,
  onSectionChange,
  completionStates,
  missingFields,
}: SectionSidebarProps) {
  return (
    <nav className="w-60 border-r border-border bg-card flex flex-col overflow-y-auto shrink-0">
      <span className="brand-caption text-muted-foreground px-4 pt-4 pb-2 block">
        Sections
      </span>
      {SECTIONS.map((section) => {
        const isActive = section.key === activeSection;
        return (
          <button
            key={section.key}
            data-active={isActive}
            onClick={() => onSectionChange(section.key)}
            className={[
              "flex items-center justify-between w-full px-4 py-3 text-sm",
              "hover:bg-background/60 transition-colors text-left",
              "border-l-2",
              isActive
                ? "border-[var(--brand-signal)] bg-background/80"
                : "border-transparent",
            ].join(" ")}
          >
            <span className="truncate pr-2">{section.label}</span>
            <CompletionBadge
              state={completionStates[section.key]}
              missingFields={missingFields[section.key]}
            />
          </button>
        );
      })}
    </nav>
  );
}
