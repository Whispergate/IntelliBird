import { DashboardShell } from "@/app/components/DashboardShell";
import { DashboardClient } from "@/app/components/DashboardClient";

export const metadata = {
  title: "Red Team Dashboard - IntelliBird",
  description: "Red Team Dashboard",
};

export default function RedPage() {
  return (
    <DashboardShell role="red">
      <DashboardClient />
    </DashboardShell>
  );
}
