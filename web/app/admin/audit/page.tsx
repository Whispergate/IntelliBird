import { auth } from "@/auth";
import AuditClient from "./AuditClient";
import { _apiFetch } from "@/app/api-client";

export default async function AuditPage() {
  const session = await auth();
  const userRole = (session?.user as { role?: string } | undefined)?.role;
  if (userRole?.toLowerCase() !== "admin") {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center space-y-2">
          <p className="text-lg font-medium text-foreground">Access Denied</p>
          <p className="text-sm text-muted-foreground">This page is restricted to Admin users.</p>
        </div>
      </div>
    );
  }

  const now = new Date();
  const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
  const initialData = await _apiFetch(
    `/api/admin/audit?limit=100&from_dt=${thirtyDaysAgo.toISOString()}&to_dt=${now.toISOString()}`
  ).then(r => r.ok ? r.json() : null).catch(() => null);

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-[22px] font-medium leading-[1.3]">Audit Log</h1>
        <p className="text-sm text-muted-foreground">Read-only record of all mutations.</p>
      </div>
      <AuditClient initialData={initialData} />
    </div>
  );
}
