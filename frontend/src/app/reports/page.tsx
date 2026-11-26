"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { Column, ReportTable } from "@/components/console/report-table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { dashboardService } from "@/services/dashboard-service";
import { AgentReport, ApplicationReport, EngineerReport, OutcomeReport, Reports } from "@/types/reports";

const RANGES = [7, 30, 90];
const AGENT_NAMES: Record<string, string> = {
  data_quality: "Data Quality",
  triage: "Triage",
  resolution: "Resolution",
  closure_quality: "Closure Quality",
  knowledge_builder: "Knowledge Builder",
};

const APPLICATIONS: Column<ApplicationReport>[] = [
  { key: "application", label: "Application" },
  { key: "opened", label: "Opened" },
  { key: "open", label: "Open now" },
  { key: "resolved", label: "Resolved" },
  { key: "p1_p2", label: "P1/P2" },
  { key: "sla_met", label: "SLA met", format: "percent" },
  { key: "mean_hours_to_resolve", label: "Mean time to resolve", format: "hours" },
  { key: "runbook_fix", label: "Runbook fix found", format: "percent" },
  { key: "kb_covered", label: "Knowledge coverage", format: "percent" },
];
const AGENTS: Column<AgentReport>[] = [
  { key: "agent", label: "Agent" },
  { key: "runs", label: "Runs" },
  { key: "model_used", label: "Model used", format: "percent" },
  { key: "model_failed", label: "Model failures" },
  { key: "tokens", label: "Tokens" },
  { key: "rated", label: "Rated" },
  { key: "correct", label: "Correct", format: "percent" },
  { key: "partially_correct", label: "Partially correct", format: "percent" },
  { key: "incorrect", label: "Incorrect", format: "percent" },
];
const OUTCOMES: Column<OutcomeReport>[] = [
  { key: "application", label: "Application" },
  { key: "fixes_confirmed", label: "Fixes confirmed" },
  { key: "first_fix", label: "First-time fix", format: "percent" },
  { key: "mean_attempts", label: "Mean attempts", format: "number" },
  { key: "escalated", label: "Escalated to lead" },
  { key: "mean_closure_score", label: "Closure score (of 6)", format: "number" },
  { key: "closure_needs_work", label: "Notes needing work", format: "percent" },
  { key: "lead_approved", label: "Lead approved" },
  { key: "lead_returned", label: "Lead returned" },
];
const ENGINEERS: Column<EngineerReport>[] = [
  { key: "engineer", label: "Engineer" },
  { key: "open", label: "Open now" },
  { key: "closed", label: "Resolved" },
  { key: "mean_hours_to_resolve", label: "Mean time to resolve", format: "hours" },
  { key: "sla_breached", label: "SLA breached" },
  { key: "priority_changes", label: "Priority changes" },
];

/** Admin reports for a period: tickets by application, agent performance, fix and closure outcomes, and engineers. */
export default function ReportsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Reports | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    dashboardService
      .getReports(days)
      .then((d) => {
        if (!current) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => current && setError(e instanceof Error ? e.message : "Couldn't load the reports. Try again."));
    return () => {
      current = false;
    };
  }, [days]);

  const shown = data?.days === days ? data : null;
  const period = `last-${days}-days`;
  return (
    <AppShell>
      <PageHeader
        title="Reports"
        context="Ticket volumes, SLA performance and agent accuracy for the selected period. Each table can be downloaded as CSV."
      />
      <Tabs value={String(days)} onValueChange={(v) => setDays(Number(v))}>
        <TabsList aria-label="Period">
          {RANGES.map((n) => (
            <TabsTrigger key={n} value={String(n)}>
              {n} days
            </TabsTrigger>
          ))}
          <TabsIndicator />
        </TabsList>
      </Tabs>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!shown && !error && <p className="text-[13px] text-muted-foreground">Loading…</p>}
      {shown && (
        <div className="flex flex-col gap-4" role="tabpanel">
          <ReportTable
            title="Tickets by application"
            description="Tickets opened in the period. Open now counts every open ticket. SLA met covers tickets whose SLA has been decided."
            columns={APPLICATIONS}
            rows={shown.applications}
            file={`tickets-by-application-${period}`}
            empty="No tickets in this period."
          />
          <ReportTable
            title="Agent performance"
            description="Runs in the period, how often the model was used, and how engineers rated the results (each person's latest rating)."
            columns={AGENTS}
            rows={shown.agents.map((a) => ({ ...a, agent: AGENT_NAMES[a.agent] ?? a.agent }))}
            file={`agent-performance-${period}`}
            empty="No agent runs in this period."
          />
          <ReportTable
            title="Resolution and closure outcomes"
            description="Fixes confirmed by engineers, how many suggestions it took, escalations, closure note quality and lead decisions."
            columns={OUTCOMES}
            rows={shown.outcomes}
            file={`resolution-and-closure-${period}`}
            empty="No confirmed fixes or closure checks in this period."
          />
          <ReportTable
            title="Engineers"
            description="Open tickets by assignee, tickets resolved in the period, SLA breaches and priority changes made in review."
            columns={ENGINEERS}
            rows={shown.engineers}
            file={`engineers-${period}`}
            empty="No assigned tickets in this period."
          />
        </div>
      )}
    </AppShell>
  );
}
