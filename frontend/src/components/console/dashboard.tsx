"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { SectionHead, Status } from "@/components/console/sync-parts";
import { dashboardService } from "@/services/dashboard-service";
import { AgentStats, DashboardSummary, SyncHealth } from "@/types/dashboard";

const POLL_MS = 30_000;

export const STAGES: [string, string][] = [
  ["pending", "Awaiting Data Quality"],
  ["awaiting_info", "Awaiting information from requester"],
  ["dq_passed", "Ready for Triage"],
  ["triaged", "Awaiting priority review"],
  ["reviewed", "In progress"],
  ["fix_confirmed", "Fix confirmed · closure note"],
  ["in_review", "Awaiting lead approval"],
  ["approved", "Approved · ready to close"],
  ["needs_lead", "Escalated to lead"],
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
        <dt className="text-muted-foreground">Model used</dt>
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

function syncWords(s: SyncHealth): { ok: boolean; text: string } {
  if (s.last_error) return { ok: false, text: `Last sync failed: ${s.last_error}` };
  if (s.state === "stale") return { ok: false, text: `Stale: last ran ${s.last_started_at ? ago(s.last_started_at) : "never"}` };
  if (s.state === "never") return { ok: false, text: "Never run" };
  if (s.state === "off") return { ok: true, text: "Manual only" };
  return { ok: true, text: `Runs every ${s.minutes === 1 ? "minute" : `${s.minutes} minutes`}` };
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

/** Sync health for the Admin's Overview: is Jira and Confluence copying on time. Read again every 30 seconds. */
export function SyncsCard() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  useEffect(() => {
    const load = () => dashboardService.getSummary().then(setData, () => {}); // a failed read keeps what is shown
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, []);
  if (!data) return null;
  return (
    <Card className="gap-0 py-0">
      <SectionHead title="Syncs" />
      <ul role="list">
        <SyncRow name="Jira" href="/settings/jira" sync={data.syncs.jira} />
        <SyncRow name="Confluence" href="/settings/confluence" sync={data.syncs.confluence} />
      </ul>
    </Card>
  );
}
