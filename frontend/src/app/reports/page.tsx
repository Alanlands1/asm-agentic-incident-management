"use client";

import { useEffect, useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { Column, ReportTable } from "@/components/console/report-table";
import { ApplicationHeatmap, BacklogAgeing, MttrByApplication, MttrByPriority, OpenedResolved, ResolvedByPriority, SlaTrend } from "@/components/reports/charts";
import { count, hours, percent } from "@/components/reports/format";
import { KpiTile } from "@/components/reports/kpi-tile";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { dashboardService } from "@/services/dashboard-service";
import { AgentReport, EngineerReport, OutcomeReport, Reports } from "@/types/reports";
import { Period, ServicePerformance } from "@/types/service";
import { cn } from "cn";

const PERIODS: { value: Period; label: string; versus: string }[] = [
  { value: "mtd", label: "Month to date", versus: "same days last month" },
  { value: "last_month", label: "Last month", versus: "the month before" },
  { value: "qtd", label: "Quarter to date", versus: "same days last quarter" },
  { value: "ytd", label: "Year to date", versus: "same days last year" },
  { value: "12m", label: "Last 12 months", versus: "the 12 months before" },
];
const SELECT =
  "h-8 rounded-lg border border-input bg-card px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";
const AGENT_NAMES: Record<string, string> = {
  data_quality: "Data Quality",
  triage: "Triage",
  resolution: "Resolution",
  closure_quality: "Closure Quality",
  knowledge_builder: "Knowledge Builder",
};

/** The change against the previous period: a share in percent for counts, in hours for MTTR, in points for rates. */
function change(now: number | null, before: number | null, kind: "count" | "hours" | "share") {
  if (now === null || before === null) return null;
  const diff = now - before;
  const sign = Math.sign(Math.round(diff * 1000));
  const signed = (v: number, unit: string) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 1 })}${unit}`;
  if (kind === "share") return { sign, text: signed(diff * 100, " pts") };
  if (kind === "hours") return { sign, text: signed(diff, " h") };
  return { sign, text: before === 0 ? signed(diff, "") : signed((diff / before) * 100, "%") };
}

/** Service performance: KPIs for the period against the one before, the last 12 months by month, and the backlog. */
export default function ReportsPage() {
  const id = useId();
  const [period, setPeriod] = useState<Period>("mtd");
  const [application, setApplication] = useState("");
  const [priority, setPriority] = useState("");
  const [data, setData] = useState<ServicePerformance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shownFor, setShownFor] = useState<string | null>(null); // the filters the numbers on screen are for
  const query = `${period}|${application}|${priority}`;
  const loading = shownFor !== query;

  useEffect(() => {
    let current = true;
    dashboardService
      .getService(period, application || undefined, priority ? Number(priority) : undefined)
      .then((d) => {
        if (!current) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => current && setError(e instanceof Error ? e.message : "Couldn't load the reports. Try again."))
      .finally(() => current && setShownFor(query));
    return () => {
      current = false;
    };
  }, [period, application, priority, query]);

  const versus = PERIODS.find((p) => p.value === period)!.versus;
  const k = data?.kpis;
  return (
    <AppShell>
      <PageHeader title="Reports" context="Service performance for the command centre: volumes, resolution times and SLA compliance, with monthly trends." />

      {/* Filters scope everything below them. */}
      <div className="flex flex-wrap items-end gap-3">
        <Tabs value={period} onValueChange={(v) => setPeriod(v as Period)}>
          <TabsList variant="pill" aria-label="Period" className="h-auto flex-wrap">
            {PERIODS.map((p) => (
              <TabsTrigger key={p.value} value={p.value}>
                {p.label}
              </TabsTrigger>
            ))}
            <TabsIndicator />
          </TabsList>
        </Tabs>
        <label htmlFor={`${id}-app`} className="sr-only">
          Application
        </label>
        <select id={`${id}-app`} className={SELECT} value={application} onChange={(e) => setApplication(e.target.value)}>
          <option value="">All applications</option>
          {data?.applications.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <label htmlFor={`${id}-priority`} className="sr-only">
          Priority
        </label>
        <select id={`${id}-priority`} className={SELECT} value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="">All priorities</option>
          {[1, 2, 3, 4, 5].map((p) => (
            <option key={p} value={p}>
              P{p}
            </option>
          ))}
        </select>
        {loading && data && <span className="text-xs text-muted-foreground">Updating…</span>}
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!data && !error && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-36 rounded-[20px]" />
          ))}
        </div>
      )}

      {data && k && (
        // Refetching keeps the frame: the last numbers stay, dimmed, until the new ones arrive.
        <div className={cn("flex flex-col gap-4 transition-opacity", loading && "opacity-60")} aria-busy={loading}>
          <section aria-label="Key figures" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <KpiTile
              label="Opened"
              value={count(k.current.opened)}
              delta={{ ...change(k.current.opened, k.previous.opened, "count")!, versus }}
              trend={k.spark.opened}
            />
            <KpiTile
              label="Resolved"
              value={count(k.current.resolved)}
              detail={`P1 ${k.current.resolved_by_priority.P1} · P2 ${k.current.resolved_by_priority.P2} · P3 ${k.current.resolved_by_priority.P3}`}
              delta={{ ...change(k.current.resolved, k.previous.resolved, "count")!, versus }}
              goodWhen="up"
              trend={k.spark.resolved}
            />
            <KpiTile label="Open backlog" value={count(k.backlog)} detail={`${k.backlog_past_sla} past SLA now`} />
            <KpiTile
              label="Mean time to resolve"
              value={hours(k.current.mttr_hours)}
              detail={`Median ${hours(k.current.median_hours)}`}
              delta={change(k.current.mttr_hours, k.previous.mttr_hours, "hours") && { ...change(k.current.mttr_hours, k.previous.mttr_hours, "hours")!, versus }}
              goodWhen="down"
              trend={k.spark.mttr_hours}
            />
            <KpiTile
              label="SLA met (P1/P2)"
              value={percent(k.current.sla_met)}
              delta={change(k.current.sla_met, k.previous.sla_met, "share") && { ...change(k.current.sla_met, k.previous.sla_met, "share")!, versus }}
              goodWhen="up"
              trend={k.spark.sla_met}
            />
            <KpiTile
              label="First-time fix"
              value={percent(k.current.first_fix)}
              detail="Fixed on the agent's first suggestion"
              delta={change(k.current.first_fix, k.previous.first_fix, "share") && { ...change(k.current.first_fix, k.previous.first_fix, "share")!, versus }}
              goodWhen="up"
              trend={k.spark.first_fix}
            />
          </section>

          <section aria-label="Monthly trends" className="grid gap-4 lg:grid-cols-2">
            <OpenedResolved data={data} />
            <ResolvedByPriority data={data} />
            <MttrByPriority data={data} />
            <SlaTrend data={data} />
            <MttrByApplication data={data} />
            <ApplicationHeatmap data={data} />
            <BacklogAgeing data={data} />
          </section>

          <Details start={data.start} end={data.end} />
        </div>
      )}
    </AppShell>
  );
}

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

/** The detailed tables, folded: agent accuracy, fix and closure outcomes, and engineers, for the same period. */
function Details({ start, end }: { start: string; end: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Reports | null>(null);
  const [error, setError] = useState<string | null>(null);
  const days = Math.max(1, Math.ceil((new Date(end).getTime() - new Date(start).getTime()) / 86_400_000));
  useEffect(() => {
    if (!open) return;
    let current = true;
    dashboardService
      .getReports(Math.min(days, 365))
      .then((d) => current && setData(d))
      .catch((e: unknown) => current && setError(e instanceof Error ? e.message : "Couldn't load the details. Try again."));
    return () => {
      current = false;
    };
  }, [open, days]);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex min-h-11 w-full items-center gap-2.5 rounded-xl border border-dashed border-border-strong px-4 py-2 text-left hover:bg-card focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        <span className="flex-1 text-[13px] font-semibold">Detailed data</span>
        <span className="text-xs text-muted-foreground">Agent performance, outcomes and engineers, with CSV</span>
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden="true" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col gap-4 pt-3">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {!data && !error && <p className="text-[13px] text-muted-foreground">Loading…</p>}
          {data && (
            <>
              <ReportTable
                title="Agent performance"
                description="Runs in the period, how often the model was used, and how engineers rated the results (each person's latest rating)."
                columns={AGENTS}
                rows={data.agents.map((a) => ({ ...a, agent: AGENT_NAMES[a.agent] ?? a.agent }))}
                file={`agent-performance-last-${days}-days`}
                empty="No agent runs in this period."
              />
              <ReportTable
                title="Resolution and closure outcomes"
                description="Fixes confirmed by engineers, how many suggestions it took, escalations, closure note quality and lead decisions."
                columns={OUTCOMES}
                rows={data.outcomes}
                file={`resolution-and-closure-last-${days}-days`}
                empty="No confirmed fixes or closure checks in this period."
              />
              <ReportTable
                title="Engineers"
                description="Open tickets by assignee, tickets resolved in the period, SLA breaches and priority changes made in review."
                columns={ENGINEERS}
                rows={data.engineers}
                file={`engineers-last-${days}-days`}
                empty="No assigned tickets in this period."
              />
            </>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
