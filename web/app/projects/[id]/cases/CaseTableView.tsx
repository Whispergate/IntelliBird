"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { CaseRow } from "@/app/api-client";

export interface CaseFilters {
  status: string;
  severity: string;
  assignee_user_sub: string;
}

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In Progress" },
  { value: "on_hold", label: "On Hold" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

const SEVERITY_OPTIONS = [
  { value: "all", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-500/20 text-red-700 border-red-500/30",
  high: "bg-orange-500/20 text-orange-700 border-orange-500/30",
  medium: "bg-yellow-500/20 text-yellow-700 border-yellow-500/30",
  low: "bg-blue-500/20 text-blue-700 border-blue-500/30",
};

const STATUS_COLORS: Record<string, string> = {
  open: "bg-green-500/20 text-green-700 border-green-500/30",
  in_progress: "bg-blue-500/20 text-blue-700 border-blue-500/30",
  on_hold: "bg-yellow-500/20 text-yellow-700 border-yellow-500/30",
  resolved: "bg-purple-500/20 text-purple-700 border-purple-500/30",
  closed: "bg-muted text-muted-foreground",
};

interface CaseTableViewProps {
  cases: CaseRow[];
  onFilterChange: (filters: CaseFilters) => void;
  projectId: string;
}

export function CaseTableView({ cases, onFilterChange, projectId }: CaseTableViewProps) {
  const [filters, setFilters] = useState<CaseFilters>({
    status: "all",
    severity: "all",
    assignee_user_sub: "",
  });
  const [assigneeInput, setAssigneeInput] = useState("");
  const [debounceTimer, setDebounceTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  function updateFilter(key: keyof CaseFilters, value: string) {
    const next = { ...filters, [key]: value };
    setFilters(next);
    onFilterChange(next);
  }

  const handleAssigneeChange = useCallback(
    (value: string) => {
      setAssigneeInput(value);
      if (debounceTimer) clearTimeout(debounceTimer);
      const timer = setTimeout(() => {
        updateFilter("assignee_user_sub", value);
      }, 300);
      setDebounceTimer(timer);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [debounceTimer, filters]
  );

  const filtered = cases.filter(c => {
    if (filters.status !== "all" && c.status !== filters.status) return false;
    if (filters.severity !== "all" && c.severity !== filters.severity) return false;
    if (
      filters.assignee_user_sub &&
      !(c.assignee_user_sub ?? "")
        .toLowerCase()
        .includes(filters.assignee_user_sub.toLowerCase())
    )
      return false;
    return true;
  });

  return (
    <div className="flex flex-col gap-3">
      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 items-center">
        <Select value={filters.status} onValueChange={v => updateFilter("status", v)}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map(o => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={filters.severity} onValueChange={v => updateFilter("severity", v)}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent>
            {SEVERITY_OPTIONS.map(o => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Input
          placeholder="Search assignee..."
          value={assigneeInput}
          onChange={e => handleAssigneeChange(e.target.value)}
          className="w-[200px]"
        />
      </div>

      {/* Table */}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Severity</TableHead>
            <TableHead>Assignee</TableHead>
            <TableHead>Opened At</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filtered.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                No cases found.
              </TableCell>
            </TableRow>
          )}
          {filtered.map(c => (
            <TableRow key={c.id} className="cursor-pointer hover:bg-muted/30">
              <TableCell>
                <Link
                  href={`/projects/${projectId}/cases/${c.id}`}
                  className="font-medium hover:underline"
                >
                  {c.title}
                </Link>
              </TableCell>
              <TableCell>
                <Badge variant="outline" className={`text-xs ${STATUS_COLORS[c.status] ?? ""}`}>
                  {c.status.replace("_", " ")}
                </Badge>
              </TableCell>
              <TableCell>
                {c.severity ? (
                  <Badge
                    variant="outline"
                    className={`text-xs ${SEVERITY_COLORS[c.severity] ?? ""}`}
                  >
                    {c.severity}
                  </Badge>
                ) : (
                  <span className="text-muted-foreground text-xs">-</span>
                )}
              </TableCell>
              <TableCell>
                <span className="text-sm text-muted-foreground">
                  {c.assignee_user_sub ?? "-"}
                </span>
              </TableCell>
              <TableCell>
                <span className="text-xs text-muted-foreground">
                  {new Date(c.opened_at).toLocaleDateString()}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
