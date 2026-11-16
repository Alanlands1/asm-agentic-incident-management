import Link from "next/link";
import { Button } from "@/components/ui/button";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { Dashboard } from "@/components/console/dashboard";

export default function Home() {
  return (
    <AppShell>
      <PageHeader
        title="Overview"
        context="Tickets from Jira and ServiceNow, and what the agents did with them today."
        actions={
          <Button variant="secondary" render={<Link href="/incidents" />} nativeButton={false}>
            Incidents
          </Button>
        }
      />
      <Dashboard />
    </AppShell>
  );
}
