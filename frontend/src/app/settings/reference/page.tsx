"use client";

import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { DocumentEditor } from "@/components/console/document-editor";
import { Tabs, TabsContent, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";

const DOCS = [
  { name: "apps", label: "Applications", note: "Application names, keywords and teams. Data Quality, Triage and privacy masking all read it." },
  { name: "pii", label: "Privacy terms", note: "Words and patterns hidden before anything is stored or sent to the model." },
  { name: "sla", label: "SLA times", note: "P1/P2 targets, when a ticket counts as at risk, and the first-message template." },
  { name: "storms", label: "Storm detection", note: "How many people, within how many minutes, make a storm." },
] as const;

/** Reference files that more than one agent reads. Tabs stay mounted so unsaved edits survive switching. */
export default function ReferenceDataPage() {
  return (
    <AppShell>
      <PageHeader title="Reference data" context="Files the agents share. Each save is checked first and recorded in the change history." />
      <Tabs defaultValue="apps">
        <TabsList aria-label="Reference files">
          {DOCS.map((d) => (
            <TabsTrigger key={d.name} value={d.name}>
              {d.label}
            </TabsTrigger>
          ))}
          <TabsIndicator />
        </TabsList>
        {DOCS.map((d) => (
          <TabsContent key={d.name} value={d.name} keepMounted>
            <DocumentEditor name={d.name} label={d.label} note={d.note} />
          </TabsContent>
        ))}
      </Tabs>
    </AppShell>
  );
}
