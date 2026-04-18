import { DashboardShell } from "@/app/components/DashboardShell";
import { DashboardClient } from "@/app/components/DashboardClient";

export const metadata = {
  title: "Blue Team Dashboard — IntelliBird",
  description: "Blue Team Dashboard",
};

export default function BluePage() {
  return (
    <DashboardShell role="blue">
      <DashboardClient />
    </DashboardShell>
  );
}
