"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { StatTile } from "@/components/console/stat-tile";
import { ListRow } from "@/components/console/list-row";
import { PriorityChip } from "@/components/console/priority-chip";
import { SectionHead, SlaClock, SlaGauge, Status } from "@/components/console/sync-parts";
import { useAttention } from "@/hooks/use-attention";
import { dashboardService } from "@/services/dashboard-service";
import { AgentStats, DashboardSummary, SyncHealth } from "@/types/dashboard";

const POLL_MS = 30_000;

export const STAGES: [string, string][] = [
  ["pending", "Waiting for Data Quality"],
  ["awaiting_info", "Needs details from the reporter"],
  ["dq_passed", "Ready for Triage"],
  ["triaged", "Waiting for an engineer"],
  ["reviewed", "Reviewed"],
  ["rejected", "Rejected"],
  ["error", "Error"],
];

const VERDICTS: Record<string, string> = { passed: "passed", needs_info: "need details", rejected: "rejected" };

const ago = (iso: string) => {
  const min = Math.max(0, Math.round((Date.now() - +new Date(iso)) / 60000));
  if (min < 60) return `${min} min ago`;
  if (min < 1440) return `${Math.floor(min / 60)} h ago`;
  return `${Math.floor(min / 1440)} d ago`;
};

export function Bars({ rows }: { rows: [string, number][] }) {
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return (
    <ul role="list" className="flex flex-col gap-2">
      {rows.map(([label, n]) => (
        <li key={label} className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)_2.5rem] md:grid-cols-[minmax(0,13rem)_minmax(0,1fr)_2.5rem] items-center gap-3 text-[13px]">
          <span className="break-words">{label}</span>
          <span className="flex h-2 overflow-hidden rounded-full bg-accent" aria-hidden="true">
            <span className="bg-foreground/70" style={{ width: `${(n / max) * 100}%` }} />
          </span>
          <span className="text-right tabular-nums text-muted-foreground">{n}</span>
        </li>
      ))}
    </ul>
  );
}

export function AgentCard({
  name,
  href,
  stats,
  linkLabel = "Settings",
}: {
  name: string;
  href: string;
  stats: AgentStats;
  linkLabel?: string;
}) {
  const verdicts = Object.entries(stats.by_verdict)
    .sort((a, b) => b[1] - a[1])
    .map(([v, n]) => `${n} ${VERDICTS[v] ?? v}`)
    .join(" · ");
  return (
    <Card className="gap-0 py-0">
      <SectionHead title={name}>
        <Link href={href} className="text-xs font-semibold text-primary underline-offset-4 hover:underline">
          {linkLabel}
        </Link>
      </SectionHead>
      <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2 px-4 py-3 text-[13px]">
        <dt className="text-muted-foreground">Checked today</dt>
        <dd className="text-right tabular-nums font-semibold">{stats.checked}</dd>
        <dt className="text-muted-foreground">Outcome</dt>
        <dd className="text-right">{verdicts || "—"}</dd>
        <dt className="text-muted-foreground">Needed the model</dt>
        <dd className="text-right tabular-nums">
          {stats.model_used}
          {stats.checked ? ` of ${stats.checked}` : ""}
        </dd>
        <dt className="text-muted-foreground">Model failures</dt>
        <dd className="text-right tabular-nums">{stats.model_failed}</dd>
      </dl>
    </Card>
  );
}

function Note({ title, big, text }: { title: string; big: React.ReactNode; text: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-[14px] bg-accent p-3.5">
      <span className="text-[13px] font-semibold">{title}</span>
      <span className="text-[26px] font-bold leading-none tabular-nums">{big}</span>
      <span className="text-xs text-muted-foreground">{text}</span>
    </div>
  );
}

const verdictCount = (a: AgentStats, v: string) => a.by_verdict[v] ?? 0;

function syncWords(s: SyncHealth): { ok: boolean; text: string } {
  if (s.last_error) return { ok: false, text: `Last sync failed: ${s.last_error}` };
  if (s.state === "stale") return { ok: false, text: `Stale: last ran ${s.last_started_at ? ago(s.last_started_at) : "never"}` };
  if (s.state === "never") return { ok: false, text: "Never ran" };
  if (s.state === "off") return { ok: true, text: "Manual only" };
  return { ok: true, text: `Running every ${s.minutes === 1 ? "minute" : `${s.minutes} minutes`}` };
}

function SyncRow({ name, href, sync }: { name: string; href: string; sync: SyncHealth }) {
  const w = syncWords(sync);
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5 text-[13px] last:border-b-0">
      <div className="min-w-0">
        <Link href={href} className="font-medium underline-offset-4 hover:underline">
          {name}
        </Link>
        <p className="text-xs text-muted-foreground">
          {[sync.last_summary, sync.last_started_at && `last ${ago(sync.last_started_at)}`].filter(Boolean).join(" · ") || "No syncs yet"}
        </p>
      </div>
      <Status ok={w.ok}>{w.text}</Status>
    </li>
  );
}

/** Admin home: live ticket flow, agent results, review queue and sync health. Refreshes every 30 seconds. */
export function Dashboard() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const load = () =>
    dashboardService
      .getSummary()
      .then((d) => {
        setData(d);
        setError(null);
        setUpdated(new Date());
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load the dashboard"));

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, []);

  const sources = data ? Object.entries(data.tickets.by_source_today).sort((a, b) => b[1] - a[1]) : [];
  const newToday = sources.reduce((n, [, c]) => n + c, 0);
  const stages = data ? STAGES.filter(([k]) => data.tickets.by_stage[k]).map(([k, label]) => [label, data.tickets.by_stage[k]] as [string, number]) : [];
  const q = data?.review_queue;
  const { data: attention } = useAttention();
  const atRisk = attention?.p1_p2 ?? [];
  const top = atRisk[0];

  return (
    <>
      <p className="-mt-2 text-xs text-muted-foreground" aria-live="polite">
        {updated ? `Updated ${updated.toLocaleTimeString()}` : "Loading…"}
      </p>

      {error && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center gap-2">
            {data ? `Couldn't refresh: ${error}. Showing the last numbers.` : error}
            <Button variant="secondary" onClick={load}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile
              variant="primary"
              label="New tickets today"
              href="/tickets"
              value={newToday}
              window={sources.map(([s, n]) => `${s} ${n}`).join(" · ") || "none yet"}
            />
            <StatTile
              label="Waiting for an engineer"
              href="/review"
              value={q!.size}
              window={q!.oldest_at ? `oldest opened ${ago(q!.oldest_at)}` : "queue is empty"}
            />
            <StatTile label="P1 and P2 in the queue" href="/incidents" value={q!.p1_p2} window="recommended by Triage" />
            <StatTile
              label="Engineers agreed"
              href="/review"
              value={data.agreement.reviewed ? `${Math.round(data.agreement.agreement * 100)}%` : "—"}
              window={`${data.agreement.reviewed} reviewed, last ${data.agreement.days} days`}
            />
          </div>

          <div className="flex flex-wrap items-stretch gap-3">
            {top && (
              <section aria-label="Most at-risk P1 or P2" className="flex max-w-sm flex-1 basis-72 flex-col gap-3.5 rounded-[20px] bg-primary p-5 text-primary-foreground">
                <h2 className="text-[13px] font-medium text-primary-foreground/80">Most at-risk P1 or P2</h2>
                <div className="self-center">
                  <SlaGauge minutesLeft={top.minutes_left} usedPercent={top.used_percent} dueAt={top.due_at} />
                </div>
                <span className="text-[17px] font-semibold">{top.summary || "No summary"}</span>
                <span className="text-[13px] text-primary-foreground/80">
                  {top.ticket_id} · {top.application ?? "No application"}
                </span>
                <Button variant="secondary" className="h-11 self-start px-5" nativeButton={false} render={<Link href={`/tickets/${encodeURIComponent(top.ticket_id)}`} />}>
                  Open ticket
                </Button>
              </section>
            )}
            <Card className="min-w-0 flex-[3_1_30rem] gap-3 p-5">
              <h2 className="text-[15px] font-semibold">What the agents did today</h2>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-3">
                <Note title="1 · Data Quality" big={data.agents.data_quality.checked} text={`checked · ${verdictCount(data.agents.data_quality, "needs_info")} need details`} />
                <Note title="2 · Triage" big={data.agents.triage.checked} text={`triaged · ${data.agents.triage.model_used} needed the model`} />
                <Note title="Review queue" big={q!.size} text={`${q!.p1_p2} are P1 or P2`} />
              </div>
            </Card>
          </div>

          {atRisk.length > 0 && (
            <Card className="gap-0 py-0">
              <SectionHead title="Open P1 and P2">
                <span className="text-xs text-muted-foreground">Most at risk first</span>
              </SectionHead>
              <ul role="list">
                {atRisk.slice(0, 6).map((i) => (
                  <ListRow
                    key={i.ticket_id}
                    lead={<PriorityChip priority={`${i.priority}`} />}
                    itemKey={i.ticket_id}
                    title={i.summary || "No summary"}
                    meta={i.application ?? "No application"}
                    trailing={<SlaClock state={i.state} minutesLeft={i.minutes_left} usedPercent={i.used_percent} />}
                    actions={
                      <Button variant="secondary" nativeButton={false} render={<Link href={`/tickets/${encodeURIComponent(i.ticket_id)}`} />}>
                        Open
                      </Button>
                    }
                  />
                ))}
              </ul>
            </Card>
          )}

          <Card className="gap-0 py-0">
            <SectionHead title="Ticket flow">
              <span className="text-xs text-muted-foreground">Open tickets by stage</span>
            </SectionHead>
            <div className="px-4 py-3">
              {stages.length ? <Bars rows={stages} /> : <p className="text-muted-foreground">No open tickets in the pipeline.</p>}
            </div>
          </Card>

          <div className="grid gap-4 md:grid-cols-2">
            <AgentCard name="Data Quality" href="/agents/data-quality" stats={data.agents.data_quality} />
            <AgentCard name="Triage" href="/agents/triage" stats={data.agents.triage} />
          </div>

          <Card className="gap-0 py-0">
            <SectionHead title="Syncs" />
            <ul role="list">
              <SyncRow name="Jira" href="/settings/jira" sync={data.syncs.jira} />
              <SyncRow name="Confluence" href="/settings/confluence" sync={data.syncs.confluence} />
            </ul>
          </Card>
        </>
      )}
    </>
  );
}
