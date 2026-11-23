"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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

const AGENT_LINES: { key: keyof Omit<Today, "closed">; name: string; done: string; flagged: (n: number) => string }[] = [
  { key: "data_quality", name: "Data Quality", done: "tickets checked", flagged: (n) => `${n} need details from the reporter` },
  { key: "triage", name: "Triage", done: "given a priority", flagged: (n) => `${n} approved without a person` },
  { key: "resolution", name: "Resolution", done: "fixes suggested", flagged: (n) => `${n} worked for the engineer` },
  { key: "closure_quality", name: "Closure Quality", done: "closure notes checked", flagged: (n) => `${n} good to send` },
  { key: "knowledge_builder", name: "Knowledge Builder", done: "closed tickets learned from", flagged: (n) => `${n} matched to an article` },
];

/** The five agents' day, one number and one line each (design canvas). */
export function AgentsToday({ today }: { today: Today | null }) {
  if (!today) return null;
  return (
    <Card className="gap-0 py-0">
      <SectionHead title="What the agents did today">
        <span className="text-xs text-muted-foreground">Personal details are masked before every model call</span>
      </SectionHead>
      <dl className="grid sm:grid-cols-2 lg:grid-cols-5">
        {AGENT_LINES.map((a) => (
          <div key={a.key} className="flex flex-col gap-0.5 border-border px-4 py-3 lg:[&+&]:border-l">
            <dt className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">{a.name}</dt>
            <dd className="text-[13px]">
              <span className="text-xl font-semibold tabular-nums">{today[a.key].done}</span> {a.done}
            </dd>
            <dd className="text-xs text-muted-foreground">{a.flagged(today[a.key].flagged)}</dd>
          </div>
        ))}
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
