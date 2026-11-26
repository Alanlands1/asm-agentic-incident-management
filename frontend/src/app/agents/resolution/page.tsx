"use client";

import Link from "next/link";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { AgentRunPanel } from "@/components/console/agent-run-panel";
import { mayOpen, useViewAs } from "@/lib/view-as";

export default function ResolutionAgentPage() {
  const role = useViewAs();
  return (
    <AppShell>
      <PageHeader
        title="Resolution"
        context="Finds the runbook fix for each ticket with a confirmed priority: the root cause, the steps and the knowledge articles used."
      />
      <AgentRunPanel agent="resolution" />
      <p className="text-xs text-muted-foreground">
        It searches the pages copied from Confluence, refreshed after each Confluence sync. If no pages are copied, it uses the runbook
        files.{" "}
        {mayOpen(role, "/settings/confluence") && (
          <Link href="/settings/confluence" className="font-semibold text-primary underline-offset-4 hover:underline">
            View copied pages
          </Link>
        )}
      </p>
    </AppShell>
  );
}
