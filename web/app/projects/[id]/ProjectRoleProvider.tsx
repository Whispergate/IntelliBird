"use client";

/**
 * ProjectRoleProvider — (UX-02).
 *
 * Client context provider that exposes the current user's per-project role
 * to any descendant client component via `useProjectRole()`.
 *
 * Role is derived server-side in layout.tsx by calling the listMemberships
 * API (RESEARCH §5 Option A — pm claim is NOT forwarded into Next.js session).
 *
 * Hierarchy (RESEARCH.md §Authority Matrix):
 *   Admin > Lead > Contributor > Observer
 *
 * Boolean cascade:
 *   isAdmin        = role === "Admin"
 *   isLead         = isAdmin || role === "Lead"
 *   isContributor  = isLead  || role === "Contributor"
 *   isObserver     = role === "Observer" || role === null   (null = least-privilege fallback)
 *
 * Usage:
 *   const { isObserver } = useProjectRole();
 *   {!isObserver && <ExportButton ... />}
 */

import { createContext, useContext, type ReactNode } from "react";

export type ProjectRoleString =
  | "Admin"
  | "Lead"
  | "Contributor"
  | "Observer"
  | null;

export interface ProjectRoleContextValue {
  role: ProjectRoleString;
  isAdmin: boolean;
  isLead: boolean;
  isContributor: boolean;
  isObserver: boolean;
}

const ProjectRoleContext = createContext<ProjectRoleContextValue | undefined>(
  undefined,
);

export function ProjectRoleProvider({
  role,
  children,
}: {
  role: ProjectRoleString;
  children: ReactNode;
}) {
  const isAdmin = role === "Admin";
  const isLead = isAdmin || role === "Lead";
  const isContributor = isLead || role === "Contributor";
  // Treat null as Observer (least-privilege: unknown role = hide privileged actions)
  const isObserver = role === "Observer" || role === null;

  return (
    <ProjectRoleContext.Provider
      value={{ role, isAdmin, isLead, isContributor, isObserver }}
    >
      {children}
    </ProjectRoleContext.Provider>
  );
}

export function useProjectRole(): ProjectRoleContextValue {
  const ctx = useContext(ProjectRoleContext);
  if (!ctx) {
    throw new Error("useProjectRole must be used within ProjectRoleProvider");
  }
  return ctx;
}
