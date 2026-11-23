"use client";

import { Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import { FeedbackStars } from "@/components/console/feedback-stars";
import { ReviewActions } from "@/components/console/review-actions";
import { RunbookButton } from "@/components/console/runbook-button";
import { SectionHead, SlaClock } from "@/components/console/sync-parts";
import { STAGES } from "@/components/console/dashboard";
import { humanize } from "@/components/console/document-hints";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableRow } from "@/components/ui/table";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api-client";
import { usePerson } from "@/lib/view-as";
import { incidentService } from "@/services/incident-service";
import { jiraService } from "@/services/jira-service";
import { pipelineService } from "@/services/pipeline-service";
import { ticketService } from "@/services/ticket-service";
import { AttentionItem } from "@/types/incident";
import { AgentRun, FixOutcome, FLAGS, Outcome, PipelineTicket } from "@/types/pipeline";
import { ServiceNowTicket } from "@/types/servicenow";
import { Check, ChevronDown, LoaderCircle, Play, Send, Star, TriangleAlert } from "lucide-react";
import { cn } from "cn";

const STAGE_WORDS: Record<string, string> = { ...Object.fromEntries(STAGES), historical: "Closed before the agents started" };
const AGENTS: Record<string, string> = {
  data_quality: "Data Quality",
  triage: "Triage",
  resolution: "Resolution",
  closure_quality: "Closure Quality",
  knowledge_builder: "Knowledge Builder",
};
const VERDICTS: Record<string, string> = {
  uncertain: "the rules could not decide",
  passed: "complete",
  needs_info: "needs details from the reporter",
  not_an_incident: "not an incident",
  rejected: "rejected",
  resolved: "found the fix in the runbooks",
  no_match: "no runbook covers this",
  good: "close notes are good",
  needs_work: "close notes need work",
  not_applicable: "close notes not needed",
  matched: "a knowledge-base article covers this fix",
  gap: "no knowledge-base article covers this fix",
};

/** What the person looking at the ticket has to do, by stage. */
const NEXT: Record<string, string> = {
  pending: "Nothing yet. The Data Quality agent checks this ticket after the next Jira sync, or run it now.",
  awaiting_info: "Ask the reporter for the missing details. The agent drafted the reply.",
  dq_passed: "Nothing yet. The Triage agent sets a priority next, or run it now.",
  triaged: "Review the recommended priority: agree with it or change it.",
  reviewed: "The priority is decided. The Resolution agent looks for the fix now.",
  fix_confirmed: "The fix worked. Finish the closure note, then send it to Jira.",
  needs_lead: "Three suggested fixes didn't work. Your lead looks at this ticket.",
  rejected: "Nothing. This is not an incident.",
  error: "An agent failed on this ticket. A person has to look.",
  historical: "Nothing. The ticket was closed before the agents started.",
};
const DQ_STEP: Record<string, ["done" | "attention", string]> = {
  passed: ["done", "Complete"],
  needs_info: ["attention", "Needs details"],
  not_an_incident: ["attention", "Not an incident"],
  rejected: ["attention", "Rejected"],
  uncertain: ["attention", "Could not decide"],
};
// Resolution, Closure Quality and Knowledge Builder: the words under their step, by verdict.
const LATER_STEP: Record<string, ["done" | "attention", string]> = {
  resolved: ["done", "Fix found"],
  matched: ["done", "Article covers it"],
  gap: ["attention", "No article yet"],
  no_match: ["attention", "No runbook covers it"],
  good: ["done", "Close notes good"],
  needs_work: ["attention", "Close notes need work"],
  not_applicable: ["done", "Not needed"],
  uncertain: ["attention", "Could not decide"],
};
// Stages where a person may start the agents; the server refuses the rest.
const CAN_RUN = ["pending", "awaiting_info", "dq_passed", "triaged", "error"];
type Agent = "data_quality" | "triage" | "resolution" | "closure_quality";
/** What an agent is doing while it runs on this ticket. */
const WORKING: Record<Agent | "knowledge_builder", string> = {
  data_quality: "Data Quality is checking the ticket…",
  triage: "Triage is setting the priority…",
  resolution: "Resolution is looking for the fix in the runbooks…",
  closure_quality: "Closure Quality is checking the close notes…",
  knowledge_builder: "Knowledge Builder is learning from the close notes…",
};

const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const show = (v: unknown) => (Array.isArray(v) ? v.join(", ") || "none" : v === null || v === "" ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : String(v));

function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <Table className="table-fixed">
      <TableBody>
        {rows.map(([k, v]) => (
          <TableRow key={k}>
            <TableHead scope="row" className="w-36 whitespace-normal px-4 text-[13px] font-normal">
              {k}
            </TableHead>
            <TableCell className="whitespace-normal">{v}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** A button that writes to the Jira issue: busy while it posts, done once it is there, the reason when it fails. */
function Post({ label, done, onPost }: { label: string; done?: boolean; onPost: () => Promise<unknown> }) {
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        disabled={busy || done || sent}
        onClick={() => {
          setBusy(true);
          setFailed(null);
          onPost()
            .then(() => setSent(true))
            .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't post to Jira"))
            .finally(() => setBusy(false));
        }}
      >
        <Send />
        {done || sent ? "Posted to Jira" : busy ? "Posting…" : label}
      </Button>
      {failed && (
        <span role="alert" className="text-xs font-medium text-destructive">
          {failed}
        </span>
      )}
    </span>
  );
}

type Audit = { model?: string; input_tokens?: number; output_tokens?: number; latency_ms?: number; attempts?: number };

/** One agent verdict: what it decided, why, and (for a model call) what it cost. */
function Run({ run, children }: { run: AgentRun; children?: React.ReactNode }) {
  const o = run.output;
  // Resolution only: runbook id -> ranking factor from engineers' ratings on tickets of the same kind.
  const weights = Object.entries((o.kb_weights ?? {}) as Record<string, number>);
  const higher = weights.filter(([, f]) => f > 1).map(([kb]) => kb);
  const lower = weights.filter(([, f]) => f < 1).map(([kb]) => kb);
  const answer = (o.answer ?? {}) as { reason?: string; missing?: string[]; chase_email?: string | null };
  // One model call for most agents; Resolution makes several and stores them as a list.
  const audits = ([] as Audit[]).concat((o.audit as Audit | Audit[] | undefined) ?? []);
  const sum = (k: "input_tokens" | "output_tokens" | "latency_ms") => audits.reduce((n, a) => n + (a[k] ?? 0), 0);
  const steps = Array.isArray(o.steps) ? (o.steps as string[]) : [];
  const references = Array.isArray(o.references) ? (o.references as string[]) : [];
  const reason = (o.reason as string | undefined) ?? answer.reason;
  const missing = [...((o.missing as string[] | undefined) ?? []), ...(answer.missing ?? [])];
  const signals = o.signals as Record<string, unknown> | undefined;
  const impact = o.impact as Record<string, { level: string; quote: string | null }> | null | undefined;
  const flags = Object.keys(FLAGS).filter((f) => o[f] === true);
  return (
    <li className="flex flex-col gap-1.5 border-b border-border px-4 py-3 text-[13px] last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold">{AGENTS[run.agent] ?? humanize(run.agent)}</span>
        <span>{/^P[1-5]$/.test(run.verdict) ? `recommends ${run.verdict}` : (VERDICTS[run.verdict] ?? run.verdict)}</span>
        <Badge variant="secondary">{o.stage === "model" || run.agent === "resolution" ? "Model" : "Rules"}</Badge>
        {flags.map((f) => (
          <Badge key={f}>{FLAGS[f]}</Badge>
        ))}
        {/* Closure Quality: the notes said the engineer followed Resolution's fix, so its cause and steps were counted */}
        {o.adopted_fix === true && <Badge variant="outline">Followed the suggested fix</Badge>}
        <span className="ml-auto text-xs text-muted-foreground">{when(run.created_at)}</span>
      </div>
      {reason && <p className="break-words">{reason}</p>}
      {impact && (
        <dl className="grid grid-cols-[minmax(0,12rem)_minmax(0,1fr)] gap-x-4 gap-y-1">
          {Object.entries(impact).map(([pillar, { level, quote }]) => (
            <div key={pillar} className="contents">
              <dt className="text-muted-foreground">{humanize(pillar)} impact</dt>
              <dd className="break-words">
                <span className="font-semibold">{humanize(level)}</span>
                {quote && <span className="text-muted-foreground"> · “{quote}”</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {typeof o.root_cause === "string" && (
        <p className="break-words">
          <span className="font-semibold">Cause: </span>
          {o.root_cause}
        </p>
      )}
      {steps.length > 0 && (
        <ol className="flex list-decimal flex-col gap-1 break-words pl-5">
          {steps.map((s, i) => (
            <li key={i}>{s.replace(/^\d+[.)]\s*/, "")}</li>
          ))}
        </ol>
      )}
      {typeof o.notes === "string" && o.notes && <p className="break-words text-muted-foreground">{o.notes}</p>}
      <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        {typeof o.rule === "string" && <span>Rule: <span className="font-mono">{o.rule}</span></span>}
        {typeof o.must_follow === "string" && <span>Must-follow rule: <span className="font-mono">{o.must_follow}</span></span>}
        {missing.length > 0 && <span>Missing: {missing.join(", ")}</span>}
        {references.length > 0 && <span>Runbook articles: <span className="font-mono">{references.join(", ")}</span></span>}
        {typeof o.confidence === "string" && <span>Confidence: {o.confidence}</span>}
        {typeof o.score === "number" && <span>Score: {o.score} of 6</span>}
        {run.agent === "knowledge_builder" && typeof o.article === "string" && <span>Article: <span className="font-mono">{o.article}</span></span>}
        {run.agent === "knowledge_builder" && typeof (o.draft as { draft_id?: number } | undefined)?.draft_id === "number" && (
          <Link href="/agents/knowledge" className="font-semibold text-primary">
            Draft #{(o.draft as { draft_id: number }).draft_id} waiting for review
          </Link>
        )}
        {audits.length > 0 && (
          <span>
            {[...new Set(audits.map((a) => a.model))].join(", ")} · {sum("input_tokens")} in / {sum("output_tokens")} out tokens ·{" "}
            {(sum("latency_ms") / 1000).toFixed(1)} s
            {audits.length > 1 ? ` · ${audits.length} model calls` : (audits[0].attempts ?? 1) > 1 ? ` · ${audits[0].attempts} attempts` : ""}
          </span>
        )}
      </p>
      {higher.length + lower.length > 0 && (
        <p className="flex flex-col gap-0.5 rounded-[14px] bg-primary px-3 py-2 text-xs text-primary-foreground">
          {higher.length > 0 && (
            <span>
              <span className="font-semibold">Ranked higher from engineers&rsquo; ratings: </span>
              <span className="font-mono">{higher.join(", ")}</span>
            </span>
          )}
          {lower.length > 0 && (
            <span>
              <span className="font-semibold">Ranked lower from engineers&rsquo; ratings: </span>
              <span className="font-mono">{lower.join(", ")}</span>
            </span>
          )}
          <span>From ratings on tickets of the same application and triage rule.</span>
        </p>
      )}
      {answer.chase_email && (
        <details>
          <summary className="cursor-pointer text-xs font-semibold text-primary">Draft reply to the reporter</summary>
          <p className="mt-1 whitespace-pre-wrap break-words rounded-lg border border-border bg-muted px-3 py-2">{answer.chase_email}</p>
        </details>
      )}
      {signals && (
        <details>
          <summary className="cursor-pointer text-xs font-semibold text-primary">What it looked at</summary>
          <dl className="mt-1 grid grid-cols-[minmax(0,12rem)_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
            {Object.entries(signals).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{humanize(k)}</dt>
                <dd className="break-words">{show(v)}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {children}
    </li>
  );
}

/** A person's note to the agents, kept on the ticket and read with the description on every run. */
function Note({
  ticketId,
  text,
  busy,
  rerun,
  inputChanged,
  onSaved,
}: {
  ticketId: string;
  text: string;
  busy: boolean;
  rerun?: () => void;
  inputChanged: boolean;
  onSaved: () => unknown;
}) {
  const [value, setValue] = useState(text);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const save = async (then: () => unknown) => {
    setSaving(true);
    setFailed(null);
    try {
      await pipelineService.setGuidance(ticketId, value);
      await then();
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "Couldn't save the note");
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-col gap-2 px-4 py-3 text-[13px]">
      <label htmlFor="note" className="font-semibold">
        Tell the agents more
      </label>
      <Textarea id="note" rows={3} maxLength={4000} value={value} onChange={(e) => setValue(e.target.value)} aria-describedby="note-help" />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" disabled={saving || value.trim() === text} onClick={() => save(onSaved)}>
          {saving ? "Saving…" : "Save note"}
        </Button>
        {rerun && (
          <Button
            size="sm"
            disabled={saving || busy || (value.trim() === text && !inputChanged)}
            title={value.trim() === text && !inputChanged ? "Nothing changed since the last run: change the note first" : undefined}
            onClick={() => save(rerun)}
          >
            <Play />
            Save and run again
          </Button>
        )}
        <span id="note-help" className="text-xs text-muted-foreground">
          Extra facts, a question, or the answer you already know. The agents read this with the description.
        </span>
      </div>
      {failed && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {failed}
        </p>
      )}
    </div>
  );
}

type StepKey = "jira" | "data_quality" | "triage" | "review" | "resolution" | "closure_quality" | "knowledge_builder" | "back";
type CardKey = "data_quality" | "triage" | "resolution" | "closure_quality" | "knowledge_builder";
type FlowState = "done" | "attention" | "waiting";

/** One stop on the step bar: what the popover says and which card "Open the section" goes to. */
interface FlowStep {
  key: StepKey;
  name: string;
  state: FlowState;
  summary: string;
  lines: string[];
  run?: AgentRun;
  /** The card this step opens; the Jira step opens the description, Back to Jira has none. */
  section: CardKey | "jira" | null;
}

const GROUPS: { label: string; keys: StepKey[] }[] = [
  { label: "Intake", keys: ["jira", "data_quality", "triage", "review"] },
  { label: "Agents", keys: ["resolution", "closure_quality"] },
  { label: "Close", keys: ["knowledge_builder", "back"] },
];
const CARDS: CardKey[] = ["data_quality", "triage", "resolution", "closure_quality", "knowledge_builder"];
const CARD_TITLES: Record<CardKey, string> = {
  data_quality: "Data Quality",
  triage: "Triage and review",
  resolution: "Suggested fix",
  closure_quality: "Close notes",
  knowledge_builder: "Knowledge",
};
const WAITS: Record<string, string> = {
  resolution: "Runs once a person has decided the priority",
  closure_quality: "Opens once you say the fix worked",
  knowledge_builder: "Runs after Closure Quality",
};

/** The reason an agent gave, cut to one popover line. */
/** The card a new read of the ticket brought a result for: an agent's new run, or the priority just decided. */
function freshCard(before: PipelineTicket | null, after: PipelineTicket): CardKey | null {
  if (!before || before.id !== after.id) return null;
  const seen = new Set(before.agent_runs.map((r) => r.id));
  const added = after.agent_runs.filter((r) => !seen.has(r.id)).at(-1);
  if (added && (CARDS as string[]).includes(added.agent)) return added.agent as CardKey;
  if (!before.decided?.final_priority && after.decided?.final_priority) return "triage";
  return null;
}

const brief = (run?: AgentRun) => {
  const o = run?.output ?? {};
  const r = (o.reason as string | undefined) ?? ((o.answer ?? {}) as { reason?: string }).reason;
  return r ? [r.length > 140 ? `${r.slice(0, 139)}…` : r] : [];
};


let glide = 0;
/** Scroll so `el` sits under the sticky top bar, eased by hand: Chrome makes `behavior: "smooth"` instant when the
 * computer asks for reduced motion. The target is read every frame, so a card that is still gliding is followed. */
function glideTo(el: HTMLElement | null, offset = 96) {
  if (!el) return;
  const from = window.scrollY;
  const id = ++glide;
  const start = performance.now();
  const frame = (now: number) => {
    if (id !== glide) return; // a newer glide took over
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const to = Math.max(0, Math.min(el.getBoundingClientRect().top + window.scrollY - offset, max));
    const t = Math.min(1, (now - start) / 550);
    window.scrollTo(0, from + (to - from) * (1 - (1 - t) ** 3));
    if (t < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

/** The circle in front of a step or card: done, needs a person, waiting, or the step to act on now. */
function StateDot({ state, now, running, n }: { state: FlowState; now?: boolean; running?: boolean; n?: number }) {
  const Icon = running ? LoaderCircle : state === "done" ? Check : state === "attention" ? TriangleAlert : null;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative flex size-[22px] shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold tabular-nums transition-colors duration-300",
        running
          ? "border-primary text-primary"
          : now
            ? "border-primary bg-primary text-primary-foreground shadow-[0_0_0_3px_var(--selected)]"
            : state === "done"
              ? "border-p3 bg-p3 text-white"
              : state === "attention"
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border-strong text-muted-foreground"
      )}
    >
      {Icon ? <Icon className={cn("size-3", running && "animate-spin")} /> : n}
      {now && !running && <span className="absolute -top-1 -right-1 size-2.5 rounded-full border-2 border-card bg-primary" />}
    </span>
  );
}

/** A step's card: one line when folded (dot, title, summary, agent), the agent's results when open. */
function StepCard({
  id,
  title,
  state,
  summary,
  badge,
  now,
  open,
  onOpenChange,
  children,
}: {
  id: CardKey;
  title: string;
  state: FlowState;
  summary: React.ReactNode;
  badge?: string;
  now?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <Card id={`step-${id}`} className={cn("scroll-mt-24 gap-0 py-0", now && "border-2 border-primary")}>
      <Collapsible open={open} onOpenChange={onOpenChange}>
        <CollapsibleTrigger className="flex min-h-11 w-full items-center gap-3 rounded-[20px] px-4 py-2.5 text-left transition-colors duration-[80ms] hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          <StateDot state={state} now={now} />
          <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
            <span className="text-sm font-semibold">{title}</span>
            <span className="text-[13px] text-muted-foreground">{summary}</span>
          </span>
          {badge && (
            <Badge variant="secondary" className="hidden sm:inline-flex">
              {badge}
            </Badge>
          )}
          <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden="true" />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="border-t border-border">{children}</div>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}

/** Replies on the ticket, and a box to add one: to the caller (on the Jira issue, only when Send is pressed) or an internal note. */
function Updates({ ticket, toJira, whyNotJira, onSent }: { ticket: PipelineTicket; toJira: boolean; whyNotJira: string; onSent: () => unknown }) {
  const person = usePerson();
  const [mode, setMode] = useState<"caller" | "internal">(toJira ? "caller" : "internal");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const caller = mode === "caller" && toJira;
  const send = () => {
    setBusy(true);
    setFailed(null);
    pipelineService
      .addComment(ticket.id, person, text.trim(), caller)
      .then(() => {
        setText("");
        return onSent();
      })
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't send the update"))
      .finally(() => setBusy(false));
  };
  return (
    <Card className="gap-0 py-0">
      <SectionHead title={`Updates (${ticket.comments.length})`} />
      {ticket.comments.length > 0 && (
        <ul role="list">
          {ticket.comments.map((c) => (
            <li key={c.id} className="flex flex-col gap-1 border-b border-border px-4 py-3 text-[13px]">
              <span className="text-xs text-muted-foreground">
                <span className="font-semibold text-foreground">{/^<[A-Z_]+_\d+>$/.test(c.author_email) ? "Reporter" : c.author_email}</span>
                {" "}· {c.from_reporter ? "reporter" : "support"} · {when(c.created_at)}
              </span>
              <p className="whitespace-pre-wrap break-words">{c.body}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-col gap-2 px-4 py-3 text-[13px]">
        <div role="group" aria-label="Who sees this" className="flex flex-wrap gap-1.5">
          <Button size="sm" variant={caller ? "default" : "secondary"} aria-pressed={caller} disabled={!toJira} title={toJira ? undefined : whyNotJira} onClick={() => setMode("caller")}>
            Reply to caller
          </Button>
          <Button size="sm" variant={caller ? "secondary" : "default"} aria-pressed={!caller} onClick={() => setMode("internal")}>
            Internal note
          </Button>
        </div>
        <label htmlFor="update" className="text-xs text-muted-foreground">
          {caller ? "The reporter sees this on the Jira issue once you press Send." : `Only people in the console see this.${toJira ? "" : ` ${whyNotJira}`}`}
        </label>
        <Textarea id="update" rows={3} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} disabled={busy} />
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={busy || !text.trim()} onClick={send}>
            <Send />
            {busy ? "Sending…" : caller ? "Send to the caller" : "Add the note"}
          </Button>
        </div>
        {failed && (
          <p role="alert" className="text-xs font-medium text-destructive">
            {failed}
          </p>
        )}
      </div>
    </Card>
  );
}

/** Who did what on the ticket, newest first: agent results, the decided priority, ratings and updates. */
function Activity({ ticket }: { ticket: PipelineTicket }) {
  const [all, setAll] = useState(false);
  const masked = (s: string) => (/^<[A-Z_]+_\d+>$/.test(s) ? "Reporter" : s);
  const decided = ticket.decided?.final_priority ? ticket.decided : null;
  const rows = [
    ...ticket.agent_runs.map((r) => ({
      key: `r${r.id}`,
      at: r.created_at,
      who: AGENTS[r.agent] ?? humanize(r.agent),
      what: /^P\d$/.test(r.verdict) ? `recommends ${r.verdict}` : (VERDICTS[r.verdict] ?? humanize(r.verdict)),
    })),
    ...(decided ? [{ key: "decided", at: decided.created_at, who: decided.reviewer, what: `decided the priority: P${decided.final_priority}` }] : []),
    ...(ticket.feedback ?? []).map((f) => ({ key: `f${f.id}`, at: f.created_at, who: f.reviewer, what: `rated ${AGENTS[f.agent] ?? humanize(f.agent)} ${f.stars} of 5` })),
    ...ticket.comments.map((c) => ({ key: `c${c.id}`, at: c.created_at, who: masked(c.author_email), what: "added an update" })),
  ]
    // The lists come oldest first; reversed, two entries with the same time keep the later one on top.
    .reverse()
    .sort((a, b) => b.at.localeCompare(a.at));
  const shown = all ? rows : rows.slice(0, 5);
  return (
    <Card className="gap-0 py-0">
      <SectionHead title="Who did what" />
      {rows.length === 0 ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">Nothing yet.</p>
      ) : (
        <ul role="list">
          {shown.map((i) => (
            <li key={i.key} className="flex flex-col gap-0.5 border-b border-border px-4 py-2.5 text-[13px] last:border-b-0 animate-in fade-in duration-500">
              <span>
                <span className="font-semibold">{i.who}</span> {i.what}
              </span>
              <span className="text-xs text-muted-foreground">{when(i.at)}</span>
            </li>
          ))}
        </ul>
      )}
      {rows.length > 5 && (
        <div className="border-t border-border px-4 py-2">
          <Button size="xs" variant="ghost" onClick={() => setAll(!all)}>
            {all ? "Show the last 5" : `Show all (${rows.length})`}
          </Button>
        </div>
      )}
    </Card>
  );
}

const GAP = /\[engineer to add: (?:cause|action|check)\]/;

/** The close notes a check said need work: start from the agent's draft (or the notes as they are), then accept or save. */
function ClosureEdit({ ticketId, run, notes, onSaved }: { ticketId: string; run: AgentRun; notes: string; onSaved: () => unknown }) {
  const person = usePerson();
  const draft = typeof run.output.draft_notes === "string" ? run.output.draft_notes : null;
  const [value, setValue] = useState(draft ?? notes);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const canAccept = draft !== null && !GAP.test(draft) && value.trim() === draft.trim();
  const decide = (action: "accepted" | "edited") => {
    setBusy(true);
    setFailed(null);
    pipelineService
      .closureReview(ticketId, { action, reviewer: person, ...(action === "edited" ? { final_text: value.trim() } : {}) })
      .then(() => {
        setSaved(action === "accepted" ? "The agent's draft is kept as the final notes." : "Your version is kept as the final notes.");
        return onSaved();
      })
      .catch((e: unknown) =>
        setFailed(e instanceof ApiError && e.status === 409 ? "Already decided for this check." : e instanceof Error ? e.message : "Couldn't save the notes")
      )
      .finally(() => setBusy(false));
  };
  return (
    <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
      <label htmlFor={`closure-${run.id}`} className="font-semibold">
        {draft ? "Close notes, as the agent would write them" : "Close notes"}
      </label>
      <p id={`closure-help-${run.id}`} className="text-xs text-muted-foreground">
        {draft && GAP.test(draft) ? "Fill in the parts marked [engineer to add: …], then save. " : ""}
        Kept in the console. They go to Jira only when you send the closure note.
      </p>
      <Textarea
        id={`closure-${run.id}`}
        rows={7}
        className="font-mono text-[12px]"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={busy || saved !== null}
        aria-describedby={`closure-help-${run.id}`}
      />
      <div className="flex flex-wrap items-center gap-2">
        {canAccept && (
          <Button size="sm" disabled={busy || saved !== null} onClick={() => decide("accepted")}>
            Accept the draft
          </Button>
        )}
        <Button
          size="sm"
          variant={canAccept ? "secondary" : "default"}
          disabled={busy || saved !== null || !value.trim() || value.trim() === notes.trim() || GAP.test(value) || (draft !== null && value.trim() === draft.trim())}
          onClick={() => decide("edited")}
        >
          {busy ? "Saving…" : "Save my version"}
        </Button>
        {saved && <span className="text-xs font-medium text-p3">{saved}</span>}
      </div>
      {failed && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {failed}
        </p>
      )}
    </div>
  );
}

const MAX_WRONG = 3; // suggested fixes that did not work before the lead looks (design D7)

/** "Did it work?" on the latest suggested fix: worked or partly opens the closure note; wrong asks for another fix. */
function FixAnswer({
  ticketId,
  run,
  version,
  answer,
  wrong,
  needsLead,
  busy,
  onDone,
}: {
  ticketId: string;
  run: AgentRun;
  version: number;
  answer?: FixOutcome;
  /** Fixes before this one that did not work. */
  wrong: number;
  needsLead: boolean;
  busy: boolean;
  onDone: () => unknown;
}) {
  const person = usePerson();
  const found = run.verdict === "resolved";
  const [mode, setMode] = useState<"partly" | "wrong" | null>(null); // writing the note that goes with the answer
  const [changing, setChanging] = useState(false);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const send = (outcome: Outcome) => {
    setSending(true);
    setFailed(null);
    pipelineService
      .fixOutcome(ticketId, { agent_run_id: run.id, outcome, reviewer: person, ...(outcome === "worked" ? {} : { note: note.trim() }) })
      .then(() => {
        setMode(null);
        setChanging(false);
        setNote("");
        return onDone();
      })
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't save your answer"))
      .finally(() => setSending(false));
  };
  const left = MAX_WRONG - wrong - 1; // new suggestions after this one, if this one did not work either
  const said = answer && answer.action !== "wrong" && !changing;
  const waitingForNext = answer?.action === "wrong" && !needsLead;
  return (
    <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">Fix v{version}</Badge>
        {waitingForNext && <span className="text-muted-foreground">You said it didn&rsquo;t work. The Resolution agent looks for another fix with what you wrote.</span>}
      </div>
      {needsLead && !said && (
        <Alert>
          <AlertDescription>
            {MAX_WRONG} suggested fixes didn&rsquo;t work. Ask your lead: they see every version and your notes. Add an internal note under Updates to bring them
            in; if you fix it together, say so here.
          </AlertDescription>
        </Alert>
      )}
      {said ? (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Check className="size-3.5 text-p3" aria-hidden="true" />
          <span className="break-words">
            {answer.action === "worked" ? "You said it worked." : found ? `You said it worked, with changes: ${answer.note}` : `You fixed it another way: ${answer.note}`}
          </span>
          <Button size="xs" variant="link" disabled={busy} onClick={() => setChanging(true)}>
            Change answer
          </Button>
        </p>
      ) : waitingForNext ? null : mode === null ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-selected px-3 py-2.5">
          <span className="font-semibold">{found ? "Did it work?" : "No runbook covers this. Fixed it another way?"}</span>
          {found && (
            <Button size="sm" disabled={busy || sending} onClick={() => send("worked")}>
              {sending ? <LoaderCircle className="animate-spin" /> : <Check />}
              {sending ? "Opening the closure note…" : "Yes, it worked"}
            </Button>
          )}
          <Button size="sm" variant="secondary" disabled={busy || sending} onClick={() => setMode("partly")}>
            {found ? "Partly, I changed steps" : "I fixed it another way"}
          </Button>
          {found && !needsLead && (
            <Button size="sm" variant="secondary" disabled={busy || sending} onClick={() => setMode("wrong")}>
              No, it didn&rsquo;t work
            </Button>
          )}
          {changing && (
            <Button size="sm" variant="ghost" disabled={sending} onClick={() => setChanging(false)}>
              Cancel
            </Button>
          )}
          <span className="basis-full text-xs text-muted-foreground">The closure note opens once you confirm the fix worked.</span>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5 rounded-xl bg-muted px-3 py-2.5 animate-in fade-in duration-300">
          <label htmlFor={`fix-note-${run.id}`} className="font-semibold">
            {mode === "wrong" ? "What happened when you tried it?" : found ? "What did you change?" : "What did you do?"}
          </label>
          <p id={`fix-note-help-${run.id}`} className="text-xs text-muted-foreground">
            {mode === "wrong"
              ? "The Resolution agent reads this and suggests a different fix. Personal details are masked before it is kept."
              : "It goes into the closure note, and the Knowledge Builder uses it to update the runbook."}
          </p>
          <Textarea
            id={`fix-note-${run.id}`}
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={sending}
            aria-describedby={`fix-note-help-${run.id}`}
            placeholder={mode === "wrong" ? "For example: the re-run failed again with the same error" : "For example: step 3 needed the file re-generated, not just re-sent"}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={busy || sending || !note.trim()} onClick={() => send(mode)}>
              {sending && <LoaderCircle className="animate-spin" />}
              {sending ? "Saving…" : mode === "partly" ? "Save and open the closure note" : left > 0 ? "Get a new suggestion" : "Ask your lead"}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={sending}
              onClick={() => {
                setMode(null);
                setNote("");
              }}
            >
              Cancel
            </Button>
            {mode === "wrong" && (
              <span className="text-xs text-muted-foreground">
                {left > 0 ? `${left} new suggestion${left === 1 ? "" : "s"} left before asking your lead` : "This is the last suggestion: your lead looks next"}
              </span>
            )}
          </div>
        </div>
      )}
      {failed && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {failed}
        </p>
      )}
    </div>
  );
}

/** The closure note once the fix worked: what Closure Quality says is missing, the note to edit, and sending it. */
function ClosureNote({
  ticket,
  run,
  toJira,
  whyNotJira,
  source,
  busy,
  onDone,
}: {
  ticket: PipelineTicket;
  run?: AgentRun;
  toJira: boolean;
  whyNotJira: string;
  source: string;
  busy: boolean;
  onDone: () => unknown;
}) {
  const person = usePerson();
  const saved = ticket.resolution_notes ?? "";
  const [value, setValue] = useState(saved);
  const [doing, setDoing] = useState<"save" | "send" | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const draft = typeof run?.output.draft_notes === "string" ? run.output.draft_notes : null;
  const questions = Array.isArray(run?.output.questions) ? (run.output.questions as string[]) : [];
  const edited = value.trim() !== saved.trim();
  const gap = GAP.test(saved);
  const call = (what: "save" | "send", request: () => Promise<unknown>) => {
    setDoing(what);
    setFailed(null);
    request()
      .then(onDone)
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : what === "save" ? "Couldn't save the note" : "Couldn't send the note"))
      .finally(() => setDoing(null));
  };
  return (
    <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
      {questions.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="font-semibold">What the note still needs</p>
          <ul className="flex list-disc flex-col gap-0.5 pl-5">
            {questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </div>
      )}
      <label htmlFor="closure-note" className="font-semibold">
        The note that goes back to {source}
      </label>
      <p id="closure-note-help" className="text-xs text-muted-foreground">
        {GAP.test(value) ? "Fill in the parts marked [engineer to add: …]. " : ""}
        Saving checks it again. It stays in the console until you send it.
      </p>
      <Textarea
        id="closure-note"
        rows={8}
        className="font-mono text-[12px]"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={doing !== null}
        aria-describedby="closure-note-help"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={edited ? "default" : "secondary"} disabled={busy || doing !== null || !edited || !value.trim()} onClick={() => call("save", () => pipelineService.saveClosureNote(ticket.id, value.trim()))}>
          {doing === "save" && <LoaderCircle className="animate-spin" />}
          {doing === "save" ? "Checking…" : "Save and check again"}
        </Button>
        {draft && draft.trim() !== value.trim() && (
          <Button size="sm" variant="secondary" disabled={doing !== null} onClick={() => setValue(draft)}>
            Use the agent&rsquo;s draft
          </Button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
        <Button size="sm" disabled={!toJira || busy || doing !== null || edited || gap || !saved.trim()} onClick={() => call("send", () => pipelineService.closeInJira(ticket.id, person))}>
          {doing === "send" ? <LoaderCircle className="animate-spin" /> : <Send />}
          {doing === "send" ? "Sending…" : `Send the closure note to ${source}`}
        </Button>
        <span className="text-xs text-muted-foreground">
          {!toJira
            ? whyNotJira
            : edited
              ? "Save your changes first."
              : gap
                ? "Fill in the marked parts first."
                : `Posts this note on ${ticket.id} and moves the issue to Done. Nothing else goes to ${source}.`}
        </span>
      </div>
      {failed && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {failed}
        </p>
      )}
    </div>
  );
}

function Text({ title, text }: { title: string; text?: string | null }) {
  return (
    <Card className="gap-0 py-0">
      <SectionHead title={title} />
      <p className="whitespace-pre-wrap break-words px-4 py-3 text-[13px]">{text || "Nothing written."}</p>
    </Card>
  );
}

function Ticket() {
  const id = decodeURIComponent(useParams<{ id: string }>().id);
  const [ticket, setTicket] = useState<PipelineTicket | null>(null);
  // Tickets loaded from a ServiceNow sheet have a list record but were never sent to the agents.
  const [sheet, setSheet] = useState<ServiceNowTicket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [site, setSite] = useState<string | null>(null);
  const [writeBack, setWriteBack] = useState(false);
  const [sla, setSla] = useState<AttentionItem | null>(null);
  const [running, setRunning] = useState<Agent | null>(null);
  const [runFailed, setRunFailed] = useState<string | null>(null);
  const person = usePerson();
  const [openStep, setOpenStep] = useState<StepKey | null>(null);
  const [openCards, setOpenCards] = useState<Set<CardKey>>(new Set());
  const [doneOpen, setDoneOpen] = useState(false);

  // Every read of the ticket goes through here, so a result that arrives is shown as just finished.
  const shown = useRef<PipelineTicket | null>(null);
  const [fresh, setFresh] = useState<CardKey | null>(null);
  const apply = useCallback((next: PipelineTicket) => {
    const finished = freshCard(shown.current, next);
    if (finished) setFresh(finished);
    shown.current = next;
    setTicket(next);
  }, []);

  const load = useCallback(
    () =>
      pipelineService
        .getTicket(id)
        .then(apply)
        .catch((e: unknown) => {
          if (!(e instanceof ApiError) || e.status !== 404) throw e;
          return ticketService.getTicket(id).then(setSheet);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : `Couldn't load ${id}`)),
    [id, apply]
  );

  useEffect(() => {
    load();
  }, [load]);

  // Live results: read the ticket again while this tab is visible, every 3 s while agents work, every 5 s while the
  // ticket is open (a Jira sync or another tab can start the agents at any time), else every 30 s.
  // A failed read keeps what is shown; the next one tries again.
  const live = ticket !== null;
  const busy = running !== null || ticket?.agents_running === true;
  const open = ticket !== null && ticket.status !== "closed" && ticket.pipeline_status !== "historical";
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => {
      if (!document.hidden) pipelineService.getTicket(id).then(apply, () => {});
    }, busy ? 3000 : open ? 5000 : 30000);
    return () => clearInterval(timer);
  }, [id, live, busy, open, apply]);

  const jira = ticket?.source === "JIRA";
  const closed = ticket?.status === "closed"; // the source decides this, not the agents' stage
  const source = jira ? "Jira" : "the source";
  useEffect(() => {
    if (jira)
      jiraService.getConnection().then(
        (c) => {
          setSite(c.site);
          setWriteBack(c.write_back === true);
        },
        () => {}
      );
  }, [jira]);

  // The SLA clock runs only on open P1/P2 tickets, which is what the Incidents list holds.
  useEffect(() => {
    if (ticket && !closed)
      incidentService.getAttention().then(
        (a) => setSla(a.p1_p2.find((i) => i.ticket_id === ticket.id) ?? null),
        () => {}
      );
  }, [ticket, closed]);

  const runAgent = (agent: Agent) => {
    setRunning(agent);
    setRunFailed(null);
    const call: Promise<unknown> =
      agent === "resolution"
        ? pipelineService.check("resolution", id)
        : agent === "closure_quality"
          ? pipelineService.check("closure", id)
          : pipelineService.runAgents(id, agent);
    call
      .then(load)
      .catch((e: unknown) => setRunFailed(e instanceof Error ? e.message : "The agent did not run"))
      .finally(() => setRunning(null));
  };
  const canRun = !closed && CAN_RUN.includes(ticket?.pipeline_status ?? "");
  // Running again only helps when the agent would see something new; an unknown answer (older backend) allows it.
  const inputChanged = (agent: Agent) => ticket?.changed?.[agent] ?? true;
  const runButton = (agent: Agent, again: boolean) => {
    const same = again && !inputChanged(agent);
    return (
      <Button
        size="xs"
        variant="secondary"
        disabled={busy || same}
        title={same ? "Nothing changed since the last run: edit the ticket, add a note or a reply first" : busy ? "The agents are working; wait for them to finish" : undefined}
        onClick={() => runAgent(agent)}
      >
        <Play />
        {again ? "Run again" : "Run"}
      </Button>
    );
  };

  const triage = ticket?.agent_runs.findLast((r) => r.agent === "triage");
  const dq = ticket?.agent_runs.findLast((r) => r.agent === "data_quality");
  // The draft reply can go to Jira only while the ticket still waits for the reporter, and only from the latest check.
  const draft = ticket?.pipeline_status === "awaiting_info" ? (dq?.output.answer as { chase_email?: string | null } | undefined)?.chase_email : null;
  const recommended = typeof triage?.output.priority === "number" ? triage.output.priority : null;
  const decided = ticket?.decided?.final_priority ? ticket.decided : null;
  // A result's rating: this person's latest, else the latest anyone gave.
  const ratingOf = (run?: AgentRun) => {
    const given = (ticket?.feedback ?? []).filter((f) => f.agent_run_id === run?.id);
    return given.findLast((f) => f.reviewer === person) ?? given.at(-1);
  };
  const rerunAgent: Agent | null = !closed && ticket?.pipeline_status === "reviewed" ? "resolution" : canRun ? "data_quality" : null;
  const rerun = rerunAgent ? () => runAgent(rerunAgent) : undefined;
  const back = (
    <Button variant="secondary" nativeButton={false} render={<Link href="/tickets" />}>
      All tickets
    </Button>
  );


  // The step bar, from the steps the console really tracks (design D4).
  const runOf = (agent: string) => ticket?.agent_runs.findLast((r) => r.agent === agent);
  // The priority is decided from here on: the fix is worked on, confirmed, or waits for the lead.
  const reviewed = ["reviewed", "fix_confirmed", "needs_lead"].includes(ticket?.pipeline_status ?? "");
  const fixing = ticket?.pipeline_status === "reviewed"; // Resolution runs only here
  const confirmed = !closed && ticket?.pipeline_status === "fix_confirmed"; // the closure note is open
  const needsLead = !closed && ticket?.pipeline_status === "needs_lead";
  const fixRuns = ticket?.agent_runs.filter((r) => r.agent === "resolution") ?? [];
  const fixRun = fixRuns.at(-1);
  const answerOf = (run?: AgentRun) => ticket?.fix_outcomes?.findLast((a) => a.agent_run_id === run?.id);
  const fixAnswer = answerOf(fixRun);
  const wrongBefore = fixRuns.slice(0, -1).filter((r) => answerOf(r)?.action === "wrong").length;
  const asking = !closed && (fixing || needsLead) && fixRun !== undefined; // waiting for the engineer's answer
  // A person reviews only a priority Triage lowered; the rest is approved by the agents.
  const autoApproved = decided?.reviewer === "AMS agents (auto)";
  const lowered = recommended !== null && ticket?.reported_priority != null && recommended > ticket.reported_priority;
  const FIX_WORDS: Record<Outcome, string> = { worked: "Fix worked", partly: "Worked, with changes", wrong: "Didn't work" };
  const fixStep = (): Partial<FlowStep> =>
    fixAnswer && fixAnswer.action !== "wrong"
      ? { state: "done", summary: FIX_WORDS[fixAnswer.action] }
      : needsLead
        ? { state: "attention", summary: "Ask your lead", lines: [`${MAX_WRONG} suggested fixes didn't work`] }
        : asking
          ? { state: "attention", summary: fixAnswer ? "Looking again" : fixRun!.verdict === "resolved" ? "Did it work?" : "No runbook covers it" }
          : {};
  const noteRun = runOf("closure_quality");
  const noteStep = (): Partial<FlowStep> =>
    confirmed
      ? {
          state: "attention",
          summary: !noteRun ? "Not checked yet" : noteRun.verdict === "good" ? "Ready to send" : (LATER_STEP[noteRun.verdict]?.[1] ?? noteRun.verdict),
          lines: [...brief(noteRun), `Goes to ${source} when you send it`],
        }
      : !["resolved", "closed"].includes(ticket?.status ?? "")
        ? { state: "waiting", summary: "Not yet", lines: [WAITS.closure_quality] }
        : {};
  const flow: FlowStep[] = ticket
    ? [
        {
          key: "jira",
          name: jira ? "Jira" : "Source",
          state: "done",
          summary: "Imported",
          lines: [`${ticket.id} from ${ticket.source}`, `Opened ${when(ticket.opened_at)}`],
          section: "jira",
        },
        {
          key: "data_quality",
          name: "Data Quality",
          state: dq ? (DQ_STEP[dq.verdict]?.[0] ?? "attention") : "waiting",
          summary: dq ? (DQ_STEP[dq.verdict]?.[1] ?? dq.verdict) : "Not yet",
          lines: dq ? [...brief(dq), when(dq.created_at)] : ["Checks the ticket after the next sync, or run it now"],
          run: dq,
          section: "data_quality",
        },
        {
          key: "triage",
          name: "Triage",
          state: recommended !== null ? "done" : triage ? "attention" : "waiting",
          summary: recommended !== null ? `P${recommended} recommended` : triage ? "Could not decide" : "Not yet",
          lines: triage ? [...brief(triage), when(triage.created_at)] : ["Sets a priority once Data Quality passes"],
          run: triage,
          section: "triage",
        },
        {
          key: "review",
          name: "Review by a person",
          state: reviewed || closed ? "done" : ticket.pipeline_status === "triaged" ? "attention" : "waiting",
          summary: autoApproved
            ? "Not needed"
            : reviewed
              ? decided?.final_priority
                ? `P${decided.final_priority} by ${decided.reviewer}`
                : "Priority decided"
              : closed
                ? "Not needed"
                : ticket.pipeline_status === "triaged"
                  ? "Waiting for you"
                  : "Only if lowered",
          lines: autoApproved
            ? [`Triage didn't lower the priority, so P${decided!.final_priority} was approved without a person`]
            : ticket.pipeline_status === "triaged" && lowered
              ? [`Triage lowered the priority from P${ticket.reported_priority} to P${recommended}: agree or change it`]
              : decided?.note
                ? [decided.note]
                : ["Needed only when Triage lowers the reporter's priority"],
          section: "triage",
        },
        ...(["resolution", "closure_quality", "knowledge_builder"] as const).map(
          (agent): FlowStep => {
            const run = runOf(agent);
            return {
              key: agent,
              name: AGENTS[agent],
              state: run ? (LATER_STEP[run.verdict]?.[0] ?? "attention") : "waiting",
              summary: run ? (LATER_STEP[run.verdict]?.[1] ?? run.verdict) : "Not yet",
              lines: run ? [...brief(run), when(run.created_at)] : [WAITS[agent]],
              run,
              section: agent,
              // The fix loop and the closure note, for tickets worked in the console.
              ...(agent === "resolution" ? fixStep() : agent === "closure_quality" ? noteStep() : {}),
            };
          }
        ),
        {
          key: "back",
          name: jira ? "Back to Jira" : "Back to the source",
          state: closed ? "done" : "waiting",
          summary: closed ? "Closed" : "At the end",
          lines: [closed ? `Closed in ${source} ${when(ticket.closed_at)}` : `The closure note goes to ${source} when you send it`],
          section: null,
        },
      ]
    : [];
  const stepOf = (key: StepKey) => flow.find((s) => s.key === key)!;
  // The step to act on: the first one not done, unless the ticket is closed.
  const nowStep = closed ? undefined : flow.find((s) => s.key !== "back" && s.state !== "done");
  const nowCard = nowStep && nowStep.section !== "jira" ? nowStep.section : null;
  // The agent working on this ticket now: a run started here, or Resolution after a priority was decided.
  // Knowledge Builder starts once the closure note is sent, when the notes passed Closure Quality.
  const working: Agent | "knowledge_builder" | null =
    running ??
    (ticket?.agents_running && fixing && !closed && (!runOf("resolution") || inputChanged("resolution"))
      ? "resolution"
      : ticket?.agents_running && closed && runOf("closure_quality")?.verdict === "good" && !runOf("knowledge_builder")
        ? "knowledge_builder"
        : null);
  const freshShown = fresh !== nowCard ? fresh : null;
  // A card's state; the Triage card covers both Triage and the person's review.
  const cardState = (key: CardKey): FlowState => {
    if (key !== "triage") return stepOf(key).state;
    const [t, r] = [stepOf("triage"), stepOf("review")];
    return r.state === "done" ? "done" : t.state === "waiting" ? "waiting" : "attention";
  };
  const cardSummary = (key: CardKey) => (key === "triage" ? `${stepOf("triage").summary} · ${stepOf("review").summary}` : stepOf(key).summary);
  // Run / Run again for an agent, where the server takes it (the same rules as before).
  const actionFor = (key: StepKey): React.ReactNode => {
    if (!ticket) return null;
    if (key === "data_quality" && canRun) return runButton("data_quality", dq !== undefined);
    if (key === "triage" && canRun && ["dq_passed", "triaged"].includes(ticket.pipeline_status)) return runButton("triage", triage !== undefined);
    if (key === "resolution" && !closed && fixing) return runButton("resolution", runOf("resolution") !== undefined);
    if (key === "closure_quality" && (confirmed || ["resolved", "closed"].includes(ticket.status)))
      return runButton("closure_quality", runOf("closure_quality") !== undefined);
    return null;
  };
  const isOpen = (key: CardKey) => key === nowCard || key === freshShown || openCards.has(key);
  const setOpen = (key: CardKey, open: boolean) =>
    setOpenCards((prev) => {
      const next = new Set(prev);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  // After the card has opened (and moved, if it did), glide to it.
  const scrollToCard = (key: CardKey | "jira") =>
    setTimeout(() => glideTo(document.getElementById(`step-${key}`)), 60);
  const openSection = (section: FlowStep["section"]) => {
    setOpenStep(null);
    if (!section) return;
    if (section !== "jira") {
      setOpen(section, true);
      if (section !== nowCard && cardState(section) === "done") setDoneOpen(true);
    }
    scrollToCard(section);
  };
  // Only once the ticket is loaded: before that there are no steps to read.
  const cardsDone = ticket ? CARDS.filter((k) => k !== nowCard && k !== freshShown && cardState(k) === "done").reverse() : []; // newest first
  const cardsNext = ticket ? CARDS.filter((k) => k !== nowCard && k !== freshShown && cardState(k) !== "done") : [];

  // One card's body: the latest result with its rating, earlier runs folded under it, and the step's own actions.
  const cardBody = (key: CardKey) => {
    const agents = key === "triage" ? ["triage"] : [key];
    const runs = ticket?.agent_runs.filter((r) => agents.includes(r.agent)) ?? [];
    const latestRun = runs.at(-1);
    const older = runs.slice(0, -1).reverse();
    const references = Array.isArray(latestRun?.output.references) ? (latestRun!.output.references as string[]) : [];
    return (
      <>
        {latestRun ? (
          <ul role="list">
            <Run run={latestRun}>
              <FeedbackStars ticketId={ticket!.id} runId={latestRun.id} given={ratingOf(latestRun)} onSent={load} />
            </Run>
          </ul>
        ) : (
          <p className="px-4 py-3 text-[13px] text-muted-foreground">{key === "triage" ? "Not triaged yet." : (WAITS[key] ?? "Not run yet.")}</p>
        )}
        {key === "resolution" && latestRun && !closed && (asking || confirmed) && (
          <FixAnswer
            key={latestRun.id}
            ticketId={ticket!.id}
            run={latestRun}
            version={runs.length}
            answer={fixAnswer}
            wrong={wrongBefore}
            needsLead={needsLead}
            busy={busy}
            onDone={load}
          />
        )}
        {key === "resolution" && references.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">From the runbooks</span>
            {references.map((kb) => (
              <RunbookButton key={kb} id={kb} panel />
            ))}
          </div>
        )}
        {key === "triage" && (
          <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
            <p>
              <span className="font-semibold">Review by a person: </span>
              {stepOf("review").summary} · {stepOf("review").lines[0]}
            </p>
            {!closed && ticket?.pipeline_status === "triaged" && recommended !== null && (
              <div className="flex flex-wrap items-center gap-2">
                <ReviewActions ticketId={ticket.id} recommended={recommended} onDone={load} />
              </div>
            )}
          </div>
        )}
        {key === "closure_quality" && confirmed ? (
          <ClosureNote
            key={ticket!.resolution_notes ?? ""}
            ticket={ticket!}
            run={latestRun}
            toJira={jira && writeBack}
            whyNotJira={jira ? "Writing to Jira is switched off for this console." : `This ticket did not come from Jira: close it in ${source} with this note.`}
            source={source}
            busy={busy}
            onDone={load}
          />
        ) : key === "closure_quality" && latestRun && ticket?.closure_decision?.agent_run_id === latestRun.id ? (
          <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
            <p className="font-semibold">
              {ticket.closure_decision.action === "accepted"
                ? "Final close notes: the agent's draft, accepted"
                : ticket.closure_decision.action === "edited"
                  ? "Final close notes: your version"
                  : "The check was set aside; the notes stand as they are"}
            </p>
            {ticket.closure_decision.final_text && (
              <p className="whitespace-pre-wrap break-words rounded-lg border border-border bg-muted px-3 py-2 font-mono text-[12px]">{ticket.closure_decision.final_text}</p>
            )}
            <p className="text-xs text-muted-foreground">Kept in the console. They go to Jira only when you send the closure note.</p>
          </div>
        ) : (
          key === "closure_quality" &&
          latestRun?.verdict === "needs_work" && (
            <ClosureEdit key={latestRun.id} ticketId={ticket!.id} run={latestRun} notes={ticket!.resolution_notes ?? ""} onSaved={load} />
          )
        )}
        {key === "data_quality" && draft && writeBack && !closed && (
          <div className="border-t border-border px-4 py-3">
            {/* Engineer-asked only (design D9): nothing goes to Jira until this is pressed. */}
            <Post label="Post the draft reply to Jira" done={ticket!.comments.some((c) => c.body.includes(draft))} onPost={() => pipelineService.replyInJira(ticket!.id, person, draft).then(load)} />
          </div>
        )}
        {older.length > 0 && (
          <Collapsible className="border-t border-border">
            <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs font-semibold text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              {key === "resolution" ? "Earlier fixes" : "Earlier checks"} ({older.length})
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul role="list" className="border-t border-border">
                {older.map((r) => {
                  const said = key === "resolution" ? answerOf(r) : undefined;
                  return (
                    <Run key={r.id} run={r}>
                      {key === "resolution" && (
                        <p className="flex flex-wrap items-center gap-2 break-words">
                          <Badge variant="secondary">Fix v{runs.indexOf(r) + 1}</Badge>
                          {said ? `${FIX_WORDS[said.action]}${said.note ? `: ${said.note}` : ""} · ${said.reviewer}` : "No answer given"}
                        </p>
                      )}
                    </Run>
                  );
                })}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        )}
      </>
    );
  };
  const card = (key: CardKey) => (
    <StepCard
      key={key}
      id={key}
      title={CARD_TITLES[key]}
      state={cardState(key)}
      summary={cardSummary(key)}
      badge={key === "triage" ? "Triage agent" : AGENTS[key] ? `${AGENTS[key]} agent` : undefined}
      now={key === nowCard}
      open={isOpen(key)}
      onOpenChange={(open) => {
        setOpen(key, open);
        if (open) scrollToCard(key);
      }}
    >
      {cardBody(key)}
    </StepCard>
  );

  // When a run moves the ticket on, bring the new step into view; not while someone is typing.
  const lastNow = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const key = nowStep?.key ?? null;
    const typing = document.activeElement instanceof HTMLTextAreaElement || document.activeElement instanceof HTMLInputElement;
    if (lastNow.current !== undefined && lastNow.current !== key && key && !typing)
      glideTo(document.getElementById("now"));
    if (ticket) lastNow.current = key;
  }, [nowStep?.key, ticket]);

  // Cards glide to their new place when they move (Now → Just finished → Coming up / Done) instead of jumping; a card
  // that appears fades up. Positions are page-relative, so scrolling doesn't count as moving.
  const places = useRef(new Map<CardKey, number>());
  const placed = useRef(false);
  useLayoutEffect(() => {
    if (!ticket) return;
    const motion = placed.current;
    for (const key of CARDS) {
      const el = document.getElementById(`step-${key}`);
      if (!el || el.offsetParent === null) continue; // not shown (e.g. folded under Done): keep where it was last seen
      // A card still gliding continues from where it is on screen.
      const moving = el.getAnimations();
      const seenAt = moving.length ? el.getBoundingClientRect().top + window.scrollY : places.current.get(key);
      moving.forEach((a) => a.cancel());
      const top = el.getBoundingClientRect().top + window.scrollY;
      places.current.set(key, top);
      if (!motion) continue;
      const ease = { duration: 550, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" };
      if (seenAt === undefined) el.animate([{ opacity: 0, transform: "translateY(12px)" }, { opacity: 1, transform: "none" }], ease);
      else if (Math.abs(seenAt - top) > 4) el.animate([{ transform: `translateY(${seenAt - top}px)` }, { transform: "none" }], ease);
    }
    placed.current = true;
  });

  return (
    <>
      <PageHeader
        title={ticket?.summary ?? sheet?.short_description ?? id}
        context={[id, ticket?.source ?? (sheet && "ServiceNow sheet"), ticket?.application ?? sheet?.service].filter(Boolean).join(" · ")}
        actions={
          <>
            {site && (
              <Button variant="secondary" nativeButton={false} render={<a href={`${site}/browse/${id}`} target="_blank" rel="noreferrer" />}>
                Open in Jira
              </Button>
            )}
            {back}
          </>
        }
      />
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!ticket && !sheet && !error && <p className="text-[13px] text-muted-foreground">Loading {id}…</p>}

      {ticket && (
        <>
          <Card id="step-jira" className="scroll-mt-24 gap-0 py-0">
            <SectionHead title="Description" />
            <p className="whitespace-pre-wrap break-words px-4 py-3 text-[13px]">{ticket.description || "Nothing written."}</p>
          </Card>

          {/* The step bar: three groups, a popover per step (click or Enter; Esc or outside closes). */}
          <Card className="scroll-thin flex-row flex-nowrap overflow-x-auto py-2" aria-label="Where the agents are" role="group">
            {GROUPS.map((group) => {
              const steps = group.keys.map(stepOf);
              const done = steps.filter((s) => s.state === "done").length;
              return (
                <div key={group.label} className="flex shrink-0 flex-auto flex-col gap-1 px-2 [&+&]:border-l [&+&]:border-border">
                  <p className="flex items-center gap-1.5 pl-1 font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">
                    {group.label}
                    <span className={done === steps.length ? "text-p3" : undefined}>{done === steps.length ? "✓ done" : `${done}/${steps.length}`}</span>
                  </p>
                  <ol role="list" className="flex flex-nowrap gap-0.5">
                    {steps.map((s) => {
                      const n = flow.indexOf(s) + 1;
                      const isNow = s === nowStep;
                      const stars = s.run ? ratingOf(s.run)?.stars : undefined;
                      const action = actionFor(s.key);
                      return (
                        <li key={s.key}>
                          <Popover open={openStep === s.key} onOpenChange={(o) => setOpenStep(o ? s.key : null)}>
                            <PopoverTrigger className="flex items-center gap-1.5 rounded-[10px] py-1 pr-1.5 pl-1 text-left transition-colors duration-[80ms] hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none data-popup-open:bg-muted">
                              <StateDot state={s.state} now={isNow} running={working === s.key} n={n} />
                              <span className="flex flex-col">
                                <span className={cn("text-xs font-semibold whitespace-nowrap", s.state === "waiting" && !isNow && "text-muted-foreground")}>{s.name}</span>
                                {isNow && <span className="text-[11px] whitespace-nowrap text-critical">{s.summary}</span>}
                              </span>
                            </PopoverTrigger>
                            <PopoverContent align="start" className="w-72 gap-2 p-3 text-[13px]">
                              <div className="flex items-center gap-2">
                                <span className="flex-1 font-mono text-[10.5px] font-medium tracking-[0.08em] text-foreground uppercase">{s.name}</span>
                                <Badge variant={isNow || s.state === "attention" ? "default" : "secondary"}>
                                  {isNow ? "Now" : s.state === "done" ? "Done" : s.state === "attention" ? "Needs a person" : "Waiting"}
                                </Badge>
                              </div>
                              <p className="text-sm font-semibold">{working === s.key ? "Running…" : s.summary}</p>
                              {s.lines.map((line, i) => (
                                <p key={i} className="break-words text-muted-foreground">
                                  {line}
                                </p>
                              ))}
                              {stars !== undefined && (
                                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                                  <Star className="size-3 fill-current text-primary" aria-hidden="true" />
                                  Rated {stars} of 5
                                </span>
                              )}
                              {(s.section || action) && (
                                <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2">
                                  {s.section && (
                                    <Button size="xs" variant="secondary" onClick={() => openSection(s.section)}>
                                      {s.section === "jira" ? "See the description" : "Open the section"}
                                    </Button>
                                  )}
                                  {action}
                                </div>
                              )}
                            </PopoverContent>
                          </Popover>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              );
            })}
          </Card>
          {runFailed && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {runFailed}
            </p>
          )}

          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="flex min-w-0 flex-col gap-4">
              {/* Now: the step to act on, open. */}
              <section id="now" aria-labelledby="now-h" className="flex scroll-mt-24 flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  {closed ? (
                    <Badge className="border-p3 bg-p3 text-white">
                      <Check aria-hidden="true" />
                      Complete
                    </Badge>
                  ) : (
                    <Badge>Now</Badge>
                  )}
                  <h2 id="now-h" className={cn("text-[13px] font-semibold", closed && "text-p3")}>
                    {nowStep ? nowStep.name : closed ? `Closed in ${source}` : "Nothing to do"}
                  </h2>
                  <span className="text-[13px] text-muted-foreground">
                    {closed
                      ? `Nothing. This ticket is closed in ${source}.`
                      : ticket.pipeline_status === "reviewed" && runOf("resolution")
                        ? fixAnswer?.action === "wrong"
                          ? "You said the fix didn't work. The Resolution agent looks for another one with what you wrote."
                          : "Try the suggested fix, then tell us if it worked. The closure note opens once it did."
                        : (NEXT[ticket.pipeline_status] ?? ticket.pipeline_status)}
                  </span>
                  {nowStep && actionFor(nowStep.key) && <span className="ml-auto">{actionFor(nowStep.key)}</span>}
                </div>
                {busy && (
                  <p role="status" className="flex items-center gap-2 text-[13px] font-medium text-primary">
                    <LoaderCircle className="size-3.5 animate-spin" />
                    {working ? WORKING[working] : "The agents are working. This page updates by itself."}
                  </p>
                )}
                {/* The placeholder slides in; a card glides here from where it was (see the layout effect above). */}
                <div
                  key={working ? `working-${working}` : `now-${nowCard}`}
                  className={working ? "animate-in fade-in slide-in-from-bottom-2 duration-500" : undefined}
                >
                  {working ? (
                    <Card className="gap-3 border-2 border-primary px-4 py-4" aria-hidden="true">
                      <Skeleton className="h-3.5 w-1/3" />
                      <Skeleton className="h-3 w-full" />
                      <Skeleton className="h-3 w-5/6" />
                      <Skeleton className="h-3 w-2/3" />
                    </Card>
                  ) : nowCard ? (
                    card(nowCard)
                  ) : (
                    closed && (
                      <Card className="flex-row items-center gap-3 border-2 border-p3 px-4 py-4 animate-in fade-in zoom-in-95 duration-500">
                        <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-full bg-p3 text-white animate-in zoom-in-50 spin-in-12 duration-700">
                          <Check className="size-5" />
                        </span>
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="text-sm font-semibold text-p3">Ticket complete</span>
                          <span className="text-[13px] text-muted-foreground">
                            {`Closed in ${source} ${when(ticket.closed_at)}.`}
                            {runOf("knowledge_builder") ? ` Knowledge Builder: ${stepOf("knowledge_builder").summary.toLowerCase()}.` : ""}
                          </span>
                        </span>
                      </Card>
                    )
                  )}
                </div>
              </section>

              {freshShown && (
                <section
                  key={`fresh-${freshShown}`}
                  aria-labelledby="fresh-h"
                  className="flex flex-col gap-2"
                >
                  <h2 id="fresh-h" className="pl-1 animate-in fade-in duration-500 font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">
                    Just finished
                  </h2>
                  {card(freshShown)}
                </section>
              )}

              {cardsNext.length > 0 && (
                <section aria-labelledby="next-h" className="flex flex-col gap-2">
                  <h2 id="next-h" className="pl-1 font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">
                    {closed ? "Needs a look" : "Coming up"}
                  </h2>
                  {cardsNext.map(card)}
                </section>
              )}

              {cardsDone.length > 0 && (
                <Collapsible open={doneOpen || closed} onOpenChange={setDoneOpen}>
                  <CollapsibleTrigger className="flex min-h-11 w-full items-center gap-2.5 rounded-xl border border-dashed border-border-strong px-4 py-2 text-left hover:bg-card focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                    <StateDot state="done" />
                    <span className="flex-1 text-[13px] font-semibold">Done · {cardsDone.length}</span>
                    <span className="text-[13px] font-semibold text-primary">{doneOpen || closed ? "Hide" : "Show"}</span>
                    <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", (doneOpen || closed) && "rotate-180")} aria-hidden="true" />
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div className="flex flex-col gap-2 pt-2">{cardsDone.map(card)}</div>
                  </CollapsibleContent>
                </Collapsible>
              )}

              {!closed && (
                <Card className="gap-0 py-0">
                  {/* Remounts when the stored note changes, so the box shows it as kept (personal details masked). */}
                  <Note key={ticket.guidance ?? ""} ticketId={ticket.id} text={ticket.guidance ?? ""} busy={busy} rerun={rerun} inputChanged={rerunAgent !== null && inputChanged(rerunAgent)} onSaved={load} />
                </Card>
              )}

              <Updates
                ticket={ticket}
                toJira={jira && writeBack && !closed}
                whyNotJira={
                  !jira
                    ? "This ticket did not come from Jira, so replies to the caller can't be sent from here."
                    : closed
                      ? `The ticket is closed in ${source}.`
                      : "Writing to Jira is switched off for this console."
                }
                onSent={load}
              />
            </div>

            <div className="flex flex-col gap-4 *:shrink-0 lg:sticky lg:top-[76px] lg:max-h-[calc(100vh-92px)] lg:overflow-y-auto lg:overscroll-contain scroll-thin">
              <Card className="gap-0 py-0">
                <SectionHead title="Details" />
                <Facts
                  rows={[
                    ["Stage", closed ? `Closed in ${source}` : (STAGE_WORDS[ticket.pipeline_status] ?? ticket.pipeline_status)],
                    ...(sla && !closed
                      ? ([["SLA", <SlaClock key="sla" state={sla.state} minutesLeft={sla.minutes_left} usedPercent={sla.used_percent} />]] as [
                          string,
                          React.ReactNode,
                        ][])
                      : []),
                    ["Recommended", recommended !== null ? <PriorityChip priority={recommended} /> : "Not triaged yet"],
                    ...(decided
                      ? [
                          [
                            "Decided",
                            <span key="d" className="inline-flex flex-wrap items-center gap-2">
                              <PriorityChip priority={decided.final_priority} />
                              {[`by ${decided.reviewer}`, decided.note].filter(Boolean).join(" · ")}
                            </span>,
                          ] as [string, React.ReactNode],
                        ]
                      : []),
                    [
                      "Reporter asked for",
                      ticket.reported_priority ? (
                        <span className="inline-flex items-center gap-2">
                          <PriorityChip priority={ticket.reported_priority} />
                          {ticket.reported_priority_label}
                        </span>
                      ) : (
                        "—"
                      ),
                    ],
                    ["Reporter", /^<[A-Z_]+_\d+>$/.test(ticket.reporter_name ?? "") ? "Name masked" : (ticket.reporter_name ?? "—")],
                    ["Assigned to", [ticket.assignment_group, ticket.assignee].filter(Boolean).join(" · ") || "—"],
                    ["Opened", when(ticket.opened_at)],
                    ...(closed ? ([["Closed", when(ticket.closed_at)]] as [string, React.ReactNode][]) : []),
                    ["Status in the source", ticket.source_status ?? ticket.status],
                  ]}
                />
              </Card>
              <Activity ticket={ticket} />
            </div>
          </div>
        </>
      )}

      {sheet && (
        <>
          <Alert>
            <AlertDescription>
              This ticket came from a ServiceNow sheet. The agents have not checked it: only tickets synced from Jira go through Data Quality
              and Triage today.
            </AlertDescription>
          </Alert>
          <Card className="gap-0 py-0">
            <SectionHead title="Ticket" />
            <Facts
              rows={[
                ["Priority", <PriorityChip key="p" priority={sheet.priority} />],
                ["Caller", sheet.caller ?? "—"],
                ["Assigned to", sheet.assignment_group ?? "—"],
                ["Opened", when(sheet.opened_at)],
                ["Closed", when(sheet.closed_at)],
                ["Rule builder", sheet.dq_flag ? `Flagged: ${sheet.dq_reason ?? "no reason given"}` : "Not flagged"],
              ]}
            />
          </Card>
          <Text title="Description" text={sheet.description} />
          {sheet.resolution_notes && <Text title="Resolution notes" text={sheet.resolution_notes} />}
        </>
      )}
    </>
  );
}

export default function TicketPage() {
  return (
    <AppShell>
      <Suspense>
        {/* Moves even when the computer asks for reduced motion (see globals.css). */}
        <div className="keep-motion contents">
          <Ticket />
        </div>
      </Suspense>
    </AppShell>
  );
}
