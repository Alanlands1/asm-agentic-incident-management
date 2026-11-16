"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { Bars } from "@/components/console/dashboard";
import { StatTile } from "@/components/console/stat-tile";
import { SectionHead } from "@/components/console/sync-parts";
import { TrendChart, short, sum } from "@/components/console/trend-chart";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { dashboardService } from "@/services/dashboard-service";
import { Trends } from "@/types/dashboard";

const RANGES = [7, 14, 30];
const SOURCES = ["JIRA", "ServiceNow", "Mailbox"];
const AGENTS: [string, string][] = [
  ["data_quality", "Data Quality"],
  ["triage", "Triage"],
];

type Series = [string, number[]][];

const total = (byName: Record<string, number[]>) => sum(Object.values(byName).flat());

function Note({ children }: { children: React.ReactNode }) {
  return <span className="text-xs text-muted-foreground">{children}</span>;
}

/** How many tickets came in, what the agents spent on the model, and where SLA times ran out, day by day. */
export default function TrendsPage() {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<Trends | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    dashboardService
      .getTrends(days)
      .then((d) => {
        if (!current) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => current && setError(e instanceof Error ? e.message : "Couldn't load the trends"));
    return () => {
      current = false;
    };
  }, [days]);

  const zeros = data ? data.days.map(() => 0) : [];
  const named = (byName: Record<string, number[]>, names: [string, string][]): Series => names.map(([key, label]) => [label, byName[key] ?? zeros]);

  const tickets: Series = data ? named(data.tickets, SOURCES.map((s) => [s, s])) : [];
  const others = data ? Object.entries(data.tickets).filter(([source]) => !SOURCES.includes(source)) : [];
  if (others.length) tickets.push(["Other", zeros.map((_, i) => sum(others.map(([, values]) => values[i])))]);

  const reviews = data ? Object.entries(data.reviews).sort((a, b) => b[1] - a[1]) : [];
  const waiting = !error && data?.days.length !== days; // the numbers on screen are for another range

  return (
    <AppShell>
      <PageHeader title="Trends" context="Tickets coming in, what the agents spend on the model, and SLA times that ran out. One column per day." />
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
          <AlertDescription>{data ? `Couldn't load ${days} days: ${error}. Showing the last numbers.` : error}</AlertDescription>
        </Alert>
      )}
      {!data && !error && <p className="text-muted-foreground">Loading…</p>}

      {data && (
        <div className={waiting ? "flex flex-col gap-4 opacity-60" : "flex flex-col gap-4"} role="tabpanel" aria-busy={waiting}>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile
              variant="primary"
              label="Tickets in"
              href="/tickets"
              value={short(total(data.tickets))}
              window={`last ${data.days.length} days`}
            />
            <StatTile
              label="Tokens used"
              value={short(data.tokens_in + data.tokens_out)}
              window={`${short(data.tokens_in)} in, ${short(data.tokens_out)} out, ${data.model_calls.toLocaleString()} model calls`}
            />
            <StatTile label="SLA times that ran out" value={total(data.sla_breaches)} window={`last ${data.days.length} days`} />
            <StatTile
              label="Open and past SLA now"
              href="/incidents"
              value={data.sla_open.breached}
              window={`${data.sla_open.breach_likely} more close to it`}
            />
          </div>

          <Card className="gap-0 py-0">
            <SectionHead title="Tickets coming in">
              <Note>By the day each ticket was opened</Note>
            </SectionHead>
            <TrendChart days={data.days} series={tickets} />
          </Card>

          <Card className="gap-0 py-0">
            <SectionHead title="Tokens used by the agents">
              <Note>Input and output together. Calls that failed are not counted</Note>
            </SectionHead>
            <TrendChart days={data.days} series={named(data.tokens, AGENTS)} />
          </Card>

          <Card className="gap-0 py-0">
            <SectionHead title="SLA breaches">
              <Note>On the day the time ran out, for P1 and P2 tickets not resolved by then</Note>
            </SectionHead>
            <TrendChart
              days={data.days}
              series={named(data.sla_breaches, [
                ["P1", "P1"],
                ["P2", "P2"],
              ])}
            />
          </Card>

          <Card className="gap-0 py-0">
            <SectionHead title="Reviews by person">
              <Note>Leads and engineers use no tokens themselves. This is the work they did</Note>
            </SectionHead>
            <div className="px-4 py-3">
              {reviews.length ? <Bars rows={reviews} /> : <p className="text-muted-foreground">No reviews in this period.</p>}
            </div>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
