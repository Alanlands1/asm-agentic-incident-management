import { ListRow } from "@/components/console/list-row";
import { cn } from "cn";
import { CircleCheck, Clock, TriangleAlert } from "lucide-react";

const SLA_WORDS = { ok: "On track", watch: "Watch", breach_likely: "Breach likely", breached: "Breached" };

/** 45 -> "45 min", 130 -> "2 h 10 min", 1923 -> "1 d 8 h". */
export const span = (minutes: number) => {
  const m = Math.abs(minutes);
  if (m < 60) return `${m} min`;
  if (m < 24 * 60) return `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
  return `${Math.floor(m / 1440)} d${Math.floor((m % 1440) / 60) ? ` ${Math.floor((m % 1440) / 60)} h` : ""}`;
};

/** When an SLA is due, in the viewer's time: "today 15:25", "tomorrow 09:10", otherwise "12 Nov 09:10". */
export const dueWords = (iso: string) => {
  const due = new Date(iso);
  const days = Math.round((new Date(iso).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86_400_000);
  const day =
    days === 0 ? "today" : days === 1 ? "tomorrow" : days === -1 ? "yesterday" : due.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return `${day} ${due.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
};

/** A ticket's SLA clock: the time left is the headline, a bar shows how much of the target is used, the state is in words. */
export function SlaClock({
  state,
  minutesLeft,
  usedPercent,
  dueAt,
}: {
  state: keyof typeof SLA_WORDS;
  minutesLeft: number;
  usedPercent?: number | null;
  dueAt?: string | null;
}) {
  const urgent = state === "breach_likely" || state === "breached";
  const Icon = urgent ? TriangleAlert : Clock;
  return (
    <div className="flex w-48 flex-col gap-1">
      <span className={cn("inline-flex items-center gap-1.5 text-sm font-semibold whitespace-nowrap tabular-nums", urgent && "text-primary")}>
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        {span(minutesLeft)} {minutesLeft < 0 ? "over" : "left"}
      </span>
      {typeof usedPercent === "number" && (
        <span className="h-1.5 overflow-hidden rounded-full bg-border" aria-hidden="true">
          <span className={cn("block h-full rounded-full", urgent ? "bg-primary" : "bg-foreground")} style={{ width: `${Math.min(usedPercent, 100)}%` }} />
        </span>
      )}
      <span className="text-xs text-muted-foreground">
        {SLA_WORDS[state]}
        {typeof usedPercent === "number" && ` · ${usedPercent}% of SLA used`}
        {dueAt && ` · ${minutesLeft < 0 ? "was due" : "due"} ${dueWords(dueAt)}`}
      </span>
    </div>
  );
}

/** The SLA as a half circle that fills with the share of the target used. It takes the colour of the box it sits in. */
export function SlaGauge({ minutesLeft, usedPercent, dueAt }: { minutesLeft: number; usedPercent: number; dueAt?: string | null }) {
  const arc = "M 16 100 A 84 84 0 0 1 184 100"; // length 264
  return (
    <div className="flex w-44 flex-col items-center gap-1 text-center">
      <svg viewBox="0 0 200 110" role="img" aria-label={`${usedPercent}% of the SLA used`} className="w-full">
        <path d={arc} fill="none" stroke="currentColor" strokeOpacity={0.25} strokeWidth={14} strokeLinecap="round" />
        <path
          d={arc}
          fill="none"
          stroke="currentColor"
          strokeWidth={14}
          strokeLinecap="round"
          strokeDasharray={264}
          strokeDashoffset={264 * (1 - Math.min(Math.max(usedPercent, 0), 100) / 100)}
          style={{ animation: "gauge-fill 900ms ease-out" }}
        />
        <text x={100} y={94} textAnchor="middle" fill="currentColor" fontSize={34} fontWeight={600}>
          {usedPercent}%
        </text>
      </svg>
      <span className="text-sm font-semibold whitespace-nowrap tabular-nums">
        {span(minutesLeft)} {minutesLeft < 0 ? "over" : "left"}
      </span>
      <span className="text-xs">
        of SLA used{dueAt && ` · ${minutesLeft < 0 ? "was due" : "due"} ${dueWords(dueAt)}`}
      </span>
    </div>
  );
}

/** Icon plus words; colour stays neutral (status is carried by the icon and text). */
export function Status({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  const Icon = ok ? CircleCheck : TriangleAlert;
  return (
    <span className="inline-flex items-center gap-1.5 text-foreground">
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      {children}
    </span>
  );
}

export function SectionHead({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </div>
  );
}

export interface SyncRun {
  id: number;
  trigger: "manual" | "schedule";
  started_at: string;
  finished_at?: string | null;
  error?: string | null;
}

/** One row per sync: what it did (summary), what it covered (scope), when and how long. */
export function SyncHistoryRow({ run, summary, scope }: { run: SyncRun; summary: string; scope: string }) {
  const took = run.finished_at ? Math.max(0, Math.round((+new Date(run.finished_at) - +new Date(run.started_at)) / 1000)) : null;
  return (
    <ListRow
      lead={run.error ? <TriangleAlert className="size-4" aria-hidden="true" /> : <CircleCheck className="size-4" aria-hidden="true" />}
      itemKey={`#${run.id}`}
      title={run.error ? `Failed: ${run.error}` : summary}
      meta={[run.trigger === "manual" ? "Manual" : "Scheduled", scope, new Date(run.started_at).toLocaleString(), took !== null && `took ${took}s`]
        .filter(Boolean)
        .join(" · ")}
    />
  );
}
