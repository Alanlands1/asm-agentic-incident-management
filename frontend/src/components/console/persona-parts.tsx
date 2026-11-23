"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, CheckCheck, Library, ShieldCheck, SlidersHorizontal, type LucideIcon } from "lucide-react";
import { CountUp } from "@/components/console/count-up";
import { ListRow } from "@/components/console/list-row";
import { STAGES } from "@/components/console/dashboard";
import { SectionHead, SlaClock } from "@/components/console/sync-parts";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { apiClient } from "@/lib/api-client";
import { cn } from "cn";

/** GET /personas/board: the open tickets with the priority in force, SLA, engineer and where the work is. */
export type Board = {
  totals: { open: number; p1_p2: number; sla_breached: number; sla_at_risk: number; waiting_review: number; unassigned: number };
  people: { name: string | null; open: number; p1_p2: number; breached: number; waiting_review: number }[];
  tickets: BoardTicket[];
};
export type BoardTicket = {
  id: string;
  summary: string | null;
  application: string | null;
  priority: number | null;
  sla_state: "ok" | "watch" | "breach_likely" | "breached" | null;
  minutes_left: number | null;
  used_percent: number | null;
  assignee: string | null;
  stage: string;
  url: string | null;
  priority_from: string | null;
  opened_at: string | null;
  triage_reason?: string | null;
  reported_priority?: number | null;
  missing?: string[];
  has_draft?: boolean;
  due_at?: string | null;
  runbook?: string | null;
  // Where the agents and people are; missing from a backend from before them.
  dq_verdict?: string | null;
  fix_verdict?: string | null;
  fix_answer?: string | null;
  fix_rated?: boolean;
  closure_verdict?: string | null;
  closure_score?: number | null;
  lead_step?: string | null;
  lead_by?: string | null;
  review_required?: boolean;
};

export const STAGE_WORDS: Record<string, string> = Object.fromEntries(STAGES);
export const NO_ENGINEER = "No engineer yet";
export const and = new Intl.ListFormat("en-GB", { type: "conjunction" });
export const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
export const appOf = (t: BoardTicket) => t.application ?? "No application";
export const ticketHref = (t: { id: string }) => `/tickets/${encodeURIComponent(t.id)}`;

/** The board, read again on demand; only the newest answer fills the page (the viewer can change while it loads). */
export function useBoard(person?: string) {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const asked = useRef(0);
  const load = useCallback(() => {
    const request = ++asked.current;
    apiClient<Board>(`/personas/board${person ? `?person=${encodeURIComponent(person)}` : ""}`)
      .then((b) => {
        if (request !== asked.current) return;
        setBoard(b);
        setError(null);
      })
      .catch((e: unknown) => {
        if (request === asked.current) setError(e instanceof Error ? e.message : "Couldn't load the board");
      });
  }, [person]);
  useEffect(load, [load]);
  return { board, error, setError, load };
}

/** The work statuses of the 19 Nov review and the design canvas, each a set of pipeline stages. */
export const STATUSES: { key: string; label: string; sub: string; stages: string[] }[] = [
  { key: "needs", label: "Needs details", sub: "reporter to answer", stages: ["awaiting_info"] },
  { key: "triage", label: "Triage", sub: "priority to agree", stages: ["pending", "dq_passed", "triaged"] },
  { key: "fixing", label: "Fixing", sub: "fix suggested", stages: ["reviewed", "needs_lead"] },
  { key: "note", label: "Closure note", sub: "being written", stages: ["fix_confirmed", "approved"] },
  { key: "review", label: "In review", sub: "with a lead", stages: ["in_review"] },
];
export const statusOf = (t: BoardTicket) => STATUSES.find((s) => s.stages.includes(t.stage));

/** The ticket's work status as a small label; the lead's step and a failed loop are named. */
export function StagePill({ ticket }: { ticket: BoardTicket }) {
  const status = statusOf(ticket);
  const words =
    ticket.stage === "needs_lead" ? "Needs the lead" : ticket.stage === "approved" ? "Ready to send" : (status?.label ?? STAGE_WORDS[ticket.stage] ?? ticket.stage);
  return (
    <Badge
      variant={status?.key === "needs" || ticket.stage === "needs_lead" ? "destructive" : status?.key === "triage" ? "outline" : "secondary"}
      className={cn((status?.key === "review" || ticket.stage === "approved") && "border-p3 text-p3")}
    >
      {words}
    </Badge>
  );
}

/** How long a ticket has been open: 40m, 5h, 3d. */
export function ageOf(t: BoardTicket, now: number) {
  if (!t.opened_at) return null;
  const opened = new Date(t.opened_at.endsWith("Z") || t.opened_at.includes("+") ? t.opened_at : `${t.opened_at}Z`).getTime();
  const minutes = Math.max(0, Math.round((now - opened) / 60000));
  return { minutes, words: minutes < 60 ? `${minutes}m` : minutes < 1440 ? `${Math.floor(minutes / 60)}h` : `${Math.floor(minutes / 1440)}d` };
}
export const AGES: { key: string; label: string; has: (minutes: number) => boolean }[] = [
  { key: "day", label: "< 1 day", has: (m) => m < 1440 },
  { key: "week", label: "1–7 days", has: (m) => m >= 1440 && m < 10080 },
  { key: "older", label: "> 7 days", has: (m) => m >= 10080 },
];

/** What the ticket waits for, as a short next step; every step is done in the console except assigning. */
export function nextStep(t: BoardTicket, toAssign = false) {
  if (toAssign) return "Assign an engineer in Jira";
  switch (t.stage) {
    case "pending":
    case "dq_passed":
      return "The agents are checking it";
    case "awaiting_info":
      return t.has_draft ? "Send the drafted question" : "Waiting for the reporter";
    case "triaged":
      return `Agree or change P${t.priority}`;
    case "reviewed":
      return !t.fix_verdict || t.fix_answer === "wrong"
        ? "Resolution is looking for a fix"
        : t.fix_verdict === "resolved"
          ? "Try the fix, say if it worked"
          : "No runbook fix: say what you did";
    case "needs_lead":
      return "The lead looks at it";
    case "fix_confirmed":
      return t.lead_step === "sent_back" ? `Answer ${t.lead_by ?? "the lead"}` : t.review_required ? "Finish the note, submit it" : "Finish the note, send it";
    case "in_review":
      return "With the lead";
    case "approved":
      return "Send the closure note";
    default:
      return STAGE_WORDS[t.stage] ?? t.stage;
  }
}

export type Task = { key: string; ticket: string; what: string; from: string };

/** The viewer's to-dos, from the tickets they work: each is one action on our ticket page. */
export function tasksOf(tickets: BoardTicket[]): Task[] {
  return tickets.flatMap((t): Task[] => {
    const tasks: Task[] = [];
    const add = (what: string, from: string) => tasks.push({ key: `${t.id} ${what}`, ticket: t.id, what, from });
    if (t.stage === "triaged")
      add(`Agree or change the priority on ${t.id}`, `Triage recommends P${t.priority}${t.reported_priority ? `; reported P${t.reported_priority}` : ""}`);
    if (t.stage === "awaiting_info" && t.has_draft) add(`Send the drafted question on ${t.id}`, "Data Quality agent drafted it");
    if (t.stage === "reviewed" && t.fix_verdict && !t.fix_answer)
      add(`Try the fix on ${t.id}, then say if it worked`, t.fix_verdict === "resolved" ? "Resolution agent suggested it" : "No runbook covers it: say what you did");
    if (t.stage === "fix_confirmed" && t.lead_step === "sent_back") add(`Answer ${t.lead_by ?? "the lead"} on ${t.id}`, `Sent back by ${t.lead_by ?? "the lead"}`);
    else if (t.stage === "fix_confirmed")
      add(
        `Finish the closure note on ${t.id}${t.review_required ? " and submit it" : ""}`,
        t.closure_score != null ? `Closure Quality scored it ${t.closure_score} of 6` : "Closure Quality agent checks it"
      );
    if (t.stage === "approved") add(`Send the closure note on ${t.id}`, `Approved by ${t.lead_by ?? "the lead"}`);
    if (t.fix_verdict === "resolved" && t.fix_answer && !t.fix_rated) add(`Rate the suggested fix on ${t.id}`, "Helps rank the runbooks");
    return tasks;
  });
}

export function Sla({ ticket }: { ticket: BoardTicket }) {
  return ticket.sla_state && ticket.minutes_left !== null ? (
    <SlaClock state={ticket.sla_state} minutesLeft={ticket.minutes_left} usedPercent={ticket.used_percent} dueAt={ticket.due_at} />
  ) : (
    <span className="text-muted-foreground">No SLA clock</span>
  );
}

type AgentDay = { done: number; flagged: number };
type Today = Record<"data_quality" | "triage" | "resolution" | "closure_quality" | "knowledge_builder", AgentDay> & { closed: number };

const midnight = () => {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
};

/** GET /personas/today, read again with the board. */
export function useToday(asOf: unknown, person?: string) {
  const [today, setToday] = useState<Today | null>(null);
  useEffect(() => {
    const who = person ? `&person=${encodeURIComponent(person)}` : "";
    apiClient<Today>(`/personas/today?since=${encodeURIComponent(midnight())}${who}`).then(setToday, () => setToday(null));
  }, [asOf, person]);
  return today;
}

// Each agent with its menu icon and pipeline step; `tone` colours the bar of its second figure.
const AGENT_LINES: {
  key: keyof Omit<Today, "closed">;
  name: string;
  Icon: LucideIcon;
  done: string;
  flagged: (n: number) => string;
  tone: string;
}[] = [
  { key: "data_quality", name: "Data Quality", Icon: ShieldCheck, done: "tickets checked", flagged: (n) => `${n} need details from the reporter`, tone: "bg-p2" },
  { key: "triage", name: "Triage", Icon: SlidersHorizontal, done: "given a priority", flagged: (n) => `${n} approved without a person`, tone: "bg-primary" },
  { key: "resolution", name: "Resolution", Icon: BookOpen, done: "fixes suggested", flagged: (n) => `${n} worked for the engineer`, tone: "bg-p3" },
  { key: "closure_quality", name: "Closure Quality", Icon: CheckCheck, done: "closure notes checked", flagged: (n) => `${n} good to send`, tone: "bg-p3" },
  { key: "knowledge_builder", name: "Knowledge Builder", Icon: Library, done: "cases learned", flagged: (n) => `${n} matched to an article`, tone: "bg-p3" },
];

/** The five agents' day, in pipeline order: a big number each, and a bar for the share behind the second line. */
export function AgentsToday({ today }: { today: Today | null }) {
  if (!today) return null;
  return (
    <Card className="gap-0 border-2 border-primary/30 py-0">
      <SectionHead title="What the agents did today">
        <span className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="hidden sm:inline">Personal details are masked before every model call</span>
          <Badge variant="outline" className="gap-1.5 border-primary/40 text-primary">
            <span aria-hidden="true" className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-primary" />
            </span>
            Live today
          </Badge>
        </span>
      </SectionHead>
      <dl className="grid sm:grid-cols-2 lg:grid-cols-5">
        {AGENT_LINES.map(({ key, name, Icon, done, flagged, tone }, i) => {
          const day = today[key];
          const share = day.done ? Math.min(100, Math.round((day.flagged / day.done) * 100)) : 0;
          return (
            <div key={key} className="flex flex-col gap-1.5 border-t border-border px-4 py-4 transition-colors duration-150 hover:bg-selected/50 sm:border-t-0 lg:[&+&]:border-l">
              <dt className="flex items-center gap-2">
                <span aria-hidden="true" className="flex size-8 shrink-0 items-center justify-center rounded-full bg-selected text-primary">
                  <Icon className="size-4" />
                </span>
                <span className="flex flex-col leading-tight">
                  <span className="font-mono text-[10px] font-medium tracking-[0.08em] text-muted-foreground uppercase">Step {i + 1}</span>
                  <span className="text-[13px] font-semibold">{name}</span>
                </span>
              </dt>
              <dd className="flex items-baseline gap-1.5">
                <span className="text-3xl font-semibold text-primary tabular-nums">
                  <CountUp value={day.done} />
                </span>
                <span className="text-[13px]">{done}</span>
              </dd>
              <dd className="flex flex-col gap-1">
                <span className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                  <span className={cn("block h-full rounded-full transition-[width] duration-700", tone)} style={{ width: `${share}%` }} />
                </span>
                <span className="text-xs text-muted-foreground">{flagged(day.flagged)}</span>
              </dd>
            </div>
          );
        })}
      </dl>
    </Card>
  );
}

type Activity = {
  at: string;
  kind: string;
  ticket_ids: string[];
  actor?: string | null;
  action?: string | null;
  priority?: number | null;
  previous_priority?: number | null;
  error?: string | null;
};

/** One activity item in words; null for a kind this page does not know. */
function sentence(a: Activity): string | null {
  const on = a.ticket_ids.length > 4 ? `${a.ticket_ids.length} tickets` : and.format(a.ticket_ids);
  const who = a.actor ?? "Someone";
  switch (a.kind) {
    case "data_quality":
      return `Data Quality ran on ${on}.`;
    case "triage":
      return `Triage ran on ${on}.`;
    case "triage_rerun":
      return !a.priority
        ? `Triage ran again on ${on}.`
        : !a.previous_priority
          ? `Triage ran again on ${on} and recommends P${a.priority}.`
          : a.previous_priority === a.priority
            ? `Triage ran again on ${on} and kept P${a.priority}.`
            : `Triage ran again on ${on} and changed P${a.previous_priority} to P${a.priority}.`;
    case "summary_sent":
      return a.actor && a.actor !== "AMS agents" ? `${a.actor} sent the agents' summary for ${on} to Jira.` : `The agents commented on ${on} in Jira.`;
    case "command_answered":
      return `Answered an "ams" command in Jira on ${on}.`;
    case "sla_warning":
      return `SLA warning posted in Jira on ${on}.`;
    case "first_message":
      return `${who} sent the first message for ${on}.`;
    case "review": {
      const priority = a.priority ? ` P${a.priority}` : " the priority";
      return a.action === "accepted"
        ? `${who} agreed with${priority} for ${on}.`
        : a.action === "edited"
          ? `${who} changed ${on} to${priority}.`
          : `${who} rejected the recommendation for ${on}${a.priority ? `;${priority} stands` : ""}.`;
    }
    case "fix_answer":
      return a.action === "wrong" ? `${who} said the fix on ${on} didn't work.` : `${who} said the fix on ${on} worked${a.action === "partly" ? ", with changes" : ""}.`;
    case "lead_review":
      return a.action === "submitted"
        ? `${who} submitted the closure note on ${on} for review.`
        : a.action === "approved"
          ? `${who} approved the closure note on ${on}.`
          : `${who} sent the closure note on ${on} back.`;
    case "closure_decision":
      return `${who} decided on the close notes of ${on}.`;
    case "closed":
      return `${who} sent the closure note and closed ${on}.`;
    case "sync_failed":
      return `Jira sync failed. ${(a.error ?? "").slice(0, 160)}`;
    default:
      return null;
  }
}

/** Today's events, newest first; `person` keeps those on their tickets. Nothing is shown when there are none. */
export function ActivityCard({ title, person, asOf }: { title: string; person?: string; asOf: unknown }) {
  const [items, setItems] = useState<Activity[]>([]);
  useEffect(() => {
    const who = person ? `&person=${encodeURIComponent(person)}` : "";
    let stale = false; // a slower answer for an earlier viewer must not replace this one
    apiClient<Activity[]>(`/personas/activity?limit=8&since=${encodeURIComponent(midnight())}${who}`)
      .then((a) => !stale && setItems(a))
      .catch(() => !stale && setItems([]));
    return () => {
      stale = true;
    };
  }, [person, asOf]);

  const lines = items.flatMap((a) => {
    const words = sentence(a);
    return words ? [{ key: `${a.kind} ${a.at} ${a.ticket_ids.join(" ")}`, at: new Date(a.at), words }] : [];
  });
  if (lines.length === 0) return null;
  return (
    <Card className="gap-0 py-0">
      <SectionHead title={title} />
      <ul role="list">
        {lines.map((line) => (
          <ListRow
            key={line.key}
            lead={
              <time dateTime={line.at.toISOString()} className="w-10 text-xs text-muted-foreground tabular-nums">
                {line.at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
              </time>
            }
            title={<span className="font-normal">{line.words}</span>}
          />
        ))}
      </ul>
    </Card>
  );
}
