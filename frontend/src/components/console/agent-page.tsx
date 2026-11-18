"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { AgentRunPanel } from "@/components/console/agent-run-panel";
import { AgentSettings } from "@/components/console/agent-settings";
import { DocumentEditor } from "@/components/console/document-editor";
import { Tabs, TabsContent, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AgentCard } from "@/components/console/dashboard";
import { dashboardService } from "@/services/dashboard-service";
import { AgentStats } from "@/types/dashboard";

export interface AgentDocument {
  name: string;
  label: string;
  note?: string;
}

/** One agent: a Settings tab, then one tab per rule or prompt file. Tabs stay mounted so unsaved edits survive switching. */
export function AgentPage({
  title,
  context,
  agent,
  prefix,
  breakerKey,
  documents,
  extra,
}: {
  agent: "data_quality" | "triage";
  title: string;
  context: string;
  prefix: "DQ" | "TRIAGE";
  breakerKey: string;
  documents: AgentDocument[];
  extra?: React.ReactNode;
}) {
  const [stats, setStats] = useState<AgentStats | null>(null);
  useEffect(() => {
    dashboardService
      .getSummary()
      .then((d) => setStats(d.agents[agent]))
      .catch(() => setStats(null)); // the settings still work without today's numbers
  }, [agent]);
  return (
    <AppShell>
      <PageHeader title={title} context={context} />
      <Tabs defaultValue="settings">
        <TabsList aria-label={`${title} sections`}>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          {documents.map((d) => (
            <TabsTrigger key={d.name} value={d.name}>
              {d.label}
            </TabsTrigger>
          ))}
          <TabsIndicator />
        </TabsList>
        <TabsContent value="settings" keepMounted>
          {stats && <AgentCard name="Today" href="/" linkLabel="Dashboard" stats={stats} />}
          <AgentRunPanel agent={agent === "data_quality" ? "data-quality" : "triage"} />
          <AgentSettings prefix={prefix} breakerKey={breakerKey} />
          {extra}
        </TabsContent>
        {documents.map((d) => (
          <TabsContent key={d.name} value={d.name} keepMounted>
            <DocumentEditor {...d} />
          </TabsContent>
        ))}
      </Tabs>
    </AppShell>
  );
}
