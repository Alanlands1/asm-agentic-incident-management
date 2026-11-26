"use client";

import { Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/console/app-shell";
import { AssignControl } from "@/components/console/assign-control";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import { FeedbackThumbs } from "@/components/console/feedback-thumbs";
import { RequesterEmail } from "@/components/console/requester-email";
import { ReviewActions } from "@/components/console/review-actions";
import { RunbookButton } from "@/components/console/runbook-button";
import { AskAssistant, FixChat } from "@/components/console/fix-chat";
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
import { usePerson, useViewAs } from "@/lib/view-as";
import { incidentService } from "@/services/incident-service";
import { jiraService } from "@/services/jira-service";
import { pipelineService } from "@/services/pipeline-service";
import { ticketService } from "@/services/ticket-service";
import { AttentionItem } from "@/types/incident";
import { AgentRun, FixOutcome, FLAGS, Outcome, PipelineTicket } from "@/types/pipeline";
import { ServiceNowTicket } from "@/types/servicenow";
import { Check, ChevronDown, Contrast, LoaderCircle, Play, Send, ThumbsDown, ThumbsUp, TriangleAlert } from "lucide-react";
import { cn } from "cn";

const STAGE_WORDS: Record<string, string> = { ...Object.fromEntries(STAGES), historical: "Closed before the agents started" };
const AGENTS: Record<string, string> = {
  data_quality: "Data Quality",
  triage: "Triage",
  resolution: "Resolution",
  closure_quality: "Closure Quality",
  knowledge_builder: "Knowledge Builder",
  fix_chat: "AI assistant",
};
const VERDICTS: Record<string, string> = {
  answered: "responded to the engineer",
  proposed: "proposed a fix",
  uncertain: "the rules were inconclusive",
  passed: "complete",
  needs_info: "needs more information from the requester",
  not_an_incident: "not an incident",
  rejected: "rejected",
  resolved: "found a fix in the runbooks",
  no_match: "no runbook covers this",
  good: "closure note meets the standard",
  needs_work: "closure note needs work",
  not_applicable: "closure note not required",
  matched: "an existing knowledge article covers this fix",
  gap: "no knowledge article covers this fix",
};

/** What the person looking at the ticket has to do, by stage. */
const NEXT: Record<string, string> = {
  pending: "No action needed yet. Data Quality checks this ticket after the next Jira sync, or you can run it now.",
  awaiting_info: "Request the missing information from the requester. A draft reply is ready.",
  dq_passed: "No action needed yet. Triage sets the priority next, or you can run it now.",
  triaged: "Review the recommended priority: accept it or change it.",
  reviewed: "Priority confirmed. Resolution is searching for a fix.",
  fix_confirmed: "Fix confirmed. Complete the closure note, then close the ticket with it.",
  needs_lead: "Three suggested fixes did not resolve the issue. The ticket is escalated to your lead.",
  in_review: "The closure note is awaiting lead approval.",
  approved: "The lead approved the closure note. Close the ticket with it.",
  rejected: "No action needed. This is not an incident.",
  error: "An agent failed on this ticket. Manual review is required.",
  historical: "No action needed. The ticket was closed before the agents started.",
};
const DQ_STEP: Record<string, ["done" | "attention", string]> = {
  passed: ["done", "Complete"],
  needs_info: ["attention", "Needs more information"],
  not_an_incident: ["attention", "Not an incident"],
  rejected: ["attention", "Rejected"],
  uncertain: ["attention", "Inconclusive"],
};
// Resolution, Closure Quality and Knowledge Builder: the words under their step, by verdict.
const LATER_STEP: Record<string, ["done" | "attention", string]> = {
  resolved: ["done", "Fix found"],
  matched: ["done", "Covered by an article"],
  gap: ["attention", "No article yet"],
  no_match: ["attention", "No matching runbook"],
  good: ["done", "Closure note complete"],
  needs_work: ["attention", "Closure note needs work"],
  not_applicable: ["done", "Not required"],
  uncertain: ["attention", "Inconclusive"],
};
// Stages where a person may start the agents; the server refuses the rest.
const CAN_RUN = ["pending", "awaiting_info", "dq_passed", "triaged", "error"];
type Agent = "data_quality" | "triage" | "resolution" | "closure_quality";
/** What an agent is doing while it runs on this ticket. */
const WORKING: Record<Agent | "knowledge_builder", string> = {
  data_quality: "Data Quality is checking the ticket…",
  triage: "Triage is setting the priority…",
  resolution: "Resolution is searching the runbooks for a fix…",
  closure_quality: "Closure Quality is checking the closure note…",
  knowledge_builder: "Knowledge Builder is learning from the closure note…",
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
            .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't post to Jira. Try again."))
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

/** One agent verdict: what it decided, why, and (for a model call) what it cost.
 *  With `action` (the question to answer on a fix), that comes right after the steps and the rest folds under it. */
function Run({ run, action, children }: { run: AgentRun; action?: React.ReactNode; children?: React.ReactNode }) {
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
  const more = (
    <>
      {typeof o.notes === "string" && o.notes && <p className="break-words text-muted-foreground">{o.notes}</p>}
      <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        {typeof o.rule === "string" && <span>Rule: <span className="font-mono">{o.rule}</span></span>}
        {typeof o.must_follow === "string" && <span>Mandatory rule: <span className="font-mono">{o.must_follow}</span></span>}
        {missing.length > 0 && <span>Missing: {missing.join(", ")}</span>}
        {references.length > 0 && <span>Runbook articles: <span className="font-mono">{references.join(", ")}</span></span>}
        {typeof o.confidence === "string" && <span>Confidence: {o.confidence}</span>}
        {typeof o.score === "number" && <span>Score: {o.score} of 6</span>}
        {run.agent === "knowledge_builder" && typeof o.article === "string" && <span>Article: <span className="font-mono">{o.article}</span></span>}
        {run.agent === "knowledge_builder" && typeof (o.draft as { draft_id?: number } | undefined)?.draft_id === "number" && (
          <Link href="/agents/knowledge" className="font-semibold text-primary">
            Draft #{(o.draft as { draft_id: number }).draft_id} awaiting review
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
              <span className="font-semibold">Ranked higher based on engineer ratings: </span>
              <span className="font-mono">{higher.join(", ")}</span>
            </span>
          )}
          {lower.length > 0 && (
            <span>
              <span className="font-semibold">Ranked lower based on engineer ratings: </span>
              <span className="font-mono">{lower.join(", ")}</span>
            </span>
          )}
          <span>Based on ratings for tickets with the same application and triage rule.</span>
        </p>
      )}
      {answer.chase_email && (
        <details>
          <summary className="cursor-pointer text-xs font-semibold text-primary">Draft reply to the requester</summary>
          <p className="mt-1 whitespace-pre-wrap break-words rounded-lg border border-border bg-muted px-3 py-2">{answer.chase_email}</p>
        </details>
      )}
      {signals && (
        <details>
          <summary className="cursor-pointer text-xs font-semibold text-primary">Signals evaluated</summary>
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
    </>
  );
  return (
    <li className="flex flex-col gap-1.5 border-b border-border px-4 py-3 text-[13px] last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold">{AGENTS[run.agent] ?? humanize(run.agent)}</span>
        <span>
          {o.source === "chat" ? "uses the fix developed with the AI assistant" : /^P[1-5]$/.test(run.verdict) ? `recommends ${run.verdict}` : (VERDICTS[run.verdict] ?? run.verdict)}
        </span>
        {o.source === "chat" && <Badge variant="outline">AI-generated, not from a runbook</Badge>}
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
          <span className="font-semibold">Root cause: </span>
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
      {action ? (
        <>
          <div className="-mx-4">{action}</div>
          <details>
            <summary className="cursor-pointer text-xs font-semibold text-primary">Why this fix was suggested</summary>
            <div className="mt-1.5 flex flex-col gap-1.5">{more}</div>
          </details>
        </>
      ) : (
        more
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
      setFailed(e instanceof Error ? e.message : "Couldn't save the note. Try again.");
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-col gap-2 px-4 py-3 text-[13px]">
      <label htmlFor="note" className="font-semibold">
        Add context for the agents
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
            title={value.trim() === text && !inputChanged ? "No changes since the last run. Update the note first." : undefined}
            onClick={() => save(rerun)}
          >
            <Play />
            Save and rerun
          </Button>
        )}
        <span id="note-help" className="text-xs text-muted-foreground">
          Additional facts, a question or a known answer. The agents read this together with the description.
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

type StepKey = "jira" | "data_quality" | "triage" | "review" | "resolution" | "closure_quality" | "lead_review" | "knowledge_builder" | "back";
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
  { label: "Close", keys: ["lead_review", "knowledge_builder", "back"] },
];
const CARDS: CardKey[] = ["data_quality", "triage", "resolution", "closure_quality", "knowledge_builder"];
const CARD_TITLES: Record<CardKey, string> = {
  data_quality: "Data Quality",
  triage: "Triage and priority review",
  resolution: "Suggested fix",
  closure_quality: "Closure note",
  knowledge_builder: "Knowledge Builder",
};
const WAITS: Record<string, string> = {
  resolution: "Runs after the priority is confirmed",
  closure_quality: "Opens after you confirm the fix",
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
function glideTo(el: HTMLElement | null, offset = 148) {  // under the top bar and the pinned (compact) step bar
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
  const Icon = running ? LoaderCircle : state === "done" ? Check : state === "attention" && !now ? TriangleAlert : null;
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
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't send the update. Try again."))
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
                <span className="font-semibold text-foreground">{/^<[A-Z_]+_\d+>$/.test(c.author_email) ? "Requester" : c.author_email}</span>
                {" "}· {c.from_reporter ? "requester" : "support"} · {when(c.created_at)}
              </span>
              <p className="whitespace-pre-wrap break-words">{c.body}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-col gap-2 px-4 py-3 text-[13px]">
        <div role="group" aria-label="Visibility" className="flex flex-wrap gap-1.5">
          <Button size="sm" variant={caller ? "default" : "secondary"} aria-pressed={caller} disabled={!toJira} title={toJira ? undefined : whyNotJira} onClick={() => setMode("caller")}>
            Reply to requester
          </Button>
          <Button size="sm" variant={caller ? "secondary" : "default"} aria-pressed={!caller} onClick={() => setMode("internal")}>
            Internal note
          </Button>
        </div>
        <label htmlFor="update" className="text-xs text-muted-foreground">
          {caller ? "The requester sees this on the Jira issue after you send it." : `Visible only in the console.${toJira ? "" : ` ${whyNotJira}`}`}
        </label>
        <Textarea id="update" rows={3} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} disabled={busy} />
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={busy || !text.trim()} onClick={send}>
            <Send />
            {busy ? "Sending…" : caller ? "Send to requester" : "Add note"}
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
  const masked = (s: string) => (/^<[A-Z_]+_\d+>$/.test(s) ? "Requester" : s);
  const decided = ticket.decided?.final_priority ? ticket.decided : null;
  const rows = [
    ...ticket.agent_runs.map((r) => ({
      key: `r${r.id}`,
      at: r.created_at,
      who: r.agent === "assignment" ? String(r.output.by) : (AGENTS[r.agent] ?? humanize(r.agent)),
      what: r.agent === "assignment" ? (r.output.to ? `assigned the ticket to ${String(r.output.to)}` : "unassigned the ticket") : /^P\d$/.test(r.verdict) ? `recommends ${r.verdict}` : (VERDICTS[r.verdict] ?? humanize(r.verdict)),
    })),
    ...(decided ? [{ key: "decided", at: decided.created_at, who: decided.reviewer, what: `confirmed the priority: P${decided.final_priority}` }] : []),
    // Ratings from use repeat what is listed already (agreed with the priority, the fix worked): only thumbs given by hand.
    ...(ticket.feedback ?? [])
      .filter((f) => !f.reason.startsWith("From use: "))
      .map((f) => ({ key: `f${f.id}`, at: f.created_at, who: f.reviewer, what: `rated ${AGENTS[f.agent] ?? humanize(f.agent)} ${f.stars >= 4 ? "correct" : f.stars <= 2 ? "incorrect" : "partially correct"}` })),
    ...ticket.comments.map((c) => ({ key: `c${c.id}`, at: c.created_at, who: masked(c.author_email), what: "added an update" })),
    ...(ticket.lead_reviews ?? []).map((s, i) => ({
      key: `l${i}`,
      at: s.created_at,
      who: s.reviewer,
      what:
        s.action === "submitted"
          ? "submitted the closure note for review"
          : s.action === "approved"
            ? "approved the closure note"
            : `returned the closure note: ${s.note ?? ""}`,
    })),
  ]
    // The lists come oldest first; reversed, two entries with the same time keep the later one on top.
    .reverse()
    .sort((a, b) => b.at.localeCompare(a.at));
  const shown = all ? rows : rows.slice(0, 5);
  return (
    <Card className="gap-0 py-0">
      <SectionHead title="Activity log" />
      {rows.length === 0 ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">No activity yet.</p>
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
            {all ? "Show latest 5" : `Show all (${rows.length})`}
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
        setSaved(action === "accepted" ? "The agent's draft is saved as the final closure note." : "Your version is saved as the final closure note.");
        return onSaved();
      })
      .catch((e: unknown) =>
        setFailed(e instanceof ApiError && e.status === 409 ? "A decision has already been recorded for this check." : e instanceof Error ? e.message : "Couldn't save the closure note. Try again.")
      )
      .finally(() => setBusy(false));
  };
  return (
    <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
      <label htmlFor={`closure-${run.id}`} className="font-semibold">
        {draft ? "Closure note, as drafted by the agent" : "Closure note"}
      </label>
      <p id={`closure-help-${run.id}`} className="text-xs text-muted-foreground">
        {draft && GAP.test(draft) ? "Complete the parts marked [engineer to add: …], then save. " : ""}
        Stored in the console. Sent to Jira only with the closure note.
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
            Accept draft
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
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't save your response. Try again."))
      .finally(() => setSending(false));
  };
  const left = MAX_WRONG - wrong - 1; // new suggestions after this one, if this one did not work either
  const said = answer && answer.action !== "wrong" && !changing;
  const waitingForNext = answer?.action === "wrong" && !needsLead;
  return (
    <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">Fix v{version}</Badge>
        {waitingForNext && <span className="text-muted-foreground">You reported that the fix did not work. Resolution is searching for another fix using your notes.</span>}
      </div>
      {needsLead && !said && (
        <Alert>
          <AlertDescription>
            {MAX_WRONG} suggested fixes did not resolve the issue. Escalate to your lead, who can see every version and your notes. Add an internal note under Updates to involve them;
            if you resolve it together, record the outcome here.
          </AlertDescription>
        </Alert>
      )}
      {said ? (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Check className="size-3.5 text-p3" aria-hidden="true" />
          <span className="break-words">
            {answer.action === "worked" ? "You confirmed the fix worked." : found ? `You confirmed the fix worked with changes: ${answer.note}` : `You resolved it another way: ${answer.note}`}
          </span>
          <Button size="xs" variant="link" disabled={busy} onClick={() => setChanging(true)}>
            Change response
          </Button>
        </p>
      ) : waitingForNext ? null : mode === null ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-selected px-3 py-2.5">
          <span className="font-semibold">{found ? "Did the fix resolve the issue?" : "No runbook covers this. Did you resolve it another way?"}</span>
          {found && (
            <Button size="sm" variant="secondary" disabled={busy || sending} onClick={() => send("worked")}>
              {sending && <LoaderCircle className="animate-spin" />}
              {sending ? "Opening the closure note…" : "Yes, resolved"}
            </Button>
          )}
          <Button size="sm" variant="secondary" disabled={busy || sending} onClick={() => setMode("partly")}>
            {found ? "Partially, with changes" : "Resolved another way"}
          </Button>
          {found && !needsLead && (
            <Button size="sm" variant="secondary" disabled={busy || sending} onClick={() => setMode("wrong")}>
              No, not resolved
            </Button>
          )}
          {changing && (
            <Button size="sm" variant="ghost" disabled={sending} onClick={() => setChanging(false)}>
              Cancel
            </Button>
          )}
          <span className="basis-full text-xs text-muted-foreground">The closure note opens after you confirm the fix.</span>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5 rounded-xl bg-muted px-3 py-2.5 animate-in fade-in duration-300">
          <label htmlFor={`fix-note-${run.id}`} className="font-semibold">
            {mode === "wrong" ? "What happened when you applied the fix?" : found ? "What did you change?" : "How did you resolve it?"}
          </label>
          <p id={`fix-note-help-${run.id}`} className="text-xs text-muted-foreground">
            {mode === "wrong"
              ? "Resolution uses this to suggest a different fix. Personal data is masked before it is stored."
              : "This is added to the closure note, and Knowledge Builder uses it to update the runbook."}
          </p>
          <Textarea
            id={`fix-note-${run.id}`}
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={sending}
            aria-describedby={`fix-note-help-${run.id}`}
            placeholder={mode === "wrong" ? "For example: the rerun failed with the same error" : "For example: step 3 required regenerating the file, not just resending it"}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={busy || sending || !note.trim()} onClick={() => send(mode)}>
              {sending && <LoaderCircle className="animate-spin" />}
              {sending ? "Saving…" : mode === "partly" ? "Save and open closure note" : left > 0 ? "Request a new suggestion" : "Escalate to lead"}
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
                {left > 0 ? `${left} more suggestion${left === 1 ? "" : "s"} before escalation to your lead` : "This is the final suggestion before escalation to your lead"}
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
  const role = useViewAs();
  const isLead = role === "lead" || role === "admin";
  const saved = ticket.resolution_notes ?? "";
  const [value, setValue] = useState(saved);
  const [doing, setDoing] = useState<"save" | "send" | "submit" | "approve" | "back" | null>(null);
  const [comment, setComment] = useState("");
  const [sendingBack, setSendingBack] = useState(false);
  const stage = ticket.pipeline_status; // fix_confirmed, in_review or approved
  const steps = ticket.lead_reviews ?? [];
  const last = steps.at(-1);
  const submitted = steps.findLast((s) => s.action === "submitted");
  const needsReview = ticket.lead_review_required === true && stage === "fix_confirmed";
  const [failed, setFailed] = useState<string | null>(null);
  const draft = typeof run?.output.draft_notes === "string" ? run.output.draft_notes : null;
  const questions = Array.isArray(run?.output.questions) ? (run.output.questions as string[]) : [];
  const edited = value.trim() !== saved.trim();
  const gap = GAP.test(saved);
  const call = (what: "save" | "send" | "submit" | "approve" | "back", request: () => Promise<unknown>) => {
    setDoing(what);
    setFailed(null);
    request()
      .then(onDone)
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : what === "save" ? "Couldn't save the note. Try again." : "Couldn't do that. Try again."))
      .finally(() => setDoing(null));
  };
  const fromJira = ticket.source === "JIRA";
  const blocked = fromJira && !toJira; // a Jira issue is closed by writing to Jira; any other ticket is closed here only
  const why = blocked ? whyNotJira : edited ? "Save your changes first." : gap ? "Complete the marked parts first." : null;
  return (
    <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
      {stage === "fix_confirmed" && last?.action === "sent_back" && (
        <div role="note" className="flex flex-col gap-0.5 rounded-xl border border-primary bg-selected px-3 py-2">
          <p className="font-semibold">Returned by {last.reviewer}</p>
          <p className="whitespace-pre-wrap break-words">{last.note}</p>
          <p className="text-xs text-muted-foreground">Update the note, save it, then resubmit it.</p>
        </div>
      )}
      {questions.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="font-semibold">Missing from the note</p>
          <ul className="flex list-disc flex-col gap-0.5 pl-5">
            {questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </div>
      )}
      <label htmlFor="closure-note" className="font-semibold">
        Closure note for {source}
      </label>
      <p id="closure-note-help" className="text-xs text-muted-foreground">
        {GAP.test(value) ? "Complete the parts marked [engineer to add: …]. " : ""}
        {stage === "in_review" ? "The lead is reviewing this note. It can't be edited during review." : "Saving runs the check again. The note stays in the console until you send it."}
      </p>
      <Textarea
        id="closure-note"
        rows={8}
        className="font-mono text-[12px]"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={doing !== null || stage === "in_review"}
        aria-describedby="closure-note-help"
      />
      {stage !== "in_review" && (
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={edited ? "default" : "secondary"} disabled={busy || doing !== null || !edited || !value.trim()} onClick={() => call("save", () => pipelineService.saveClosureNote(ticket.id, value.trim()))}>
          {doing === "save" && <LoaderCircle className="animate-spin" />}
          {doing === "save" ? "Checking…" : "Save and recheck"}
        </Button>
        {draft && draft.trim() !== value.trim() && (
          <Button size="sm" variant="secondary" disabled={doing !== null} onClick={() => setValue(draft)}>
            Use agent draft
          </Button>
        )}
        {stage === "approved" && <span className="text-xs text-muted-foreground">Saving a change resubmits it for lead approval.</span>}
      </div>
      )}
      {stage === "in_review" ? (
        <div className="flex flex-col gap-2 border-t border-border pt-2.5">
          <p>
            <span className="font-semibold">Awaiting lead approval.</span>{" "}
            <span className="text-muted-foreground">Submitted by {submitted?.reviewer ?? "the engineer"} {submitted ? when(submitted.created_at) : ""}.</span>
          </p>
          {isLead ? (
            sendingBack ? (
              <div className="flex flex-col gap-1.5 rounded-xl bg-muted px-3 py-2.5 animate-in fade-in duration-300">
                <label htmlFor="send-back" className="font-semibold">
                  What should the engineer change?
                </label>
                <Textarea id="send-back" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} disabled={doing !== null} />
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" disabled={doing !== null || !comment.trim()} onClick={() => call("back", () => pipelineService.leadReview(ticket.id, { action: "sent_back", note: comment.trim(), reviewer: person }))}>
                    {doing === "back" && <LoaderCircle className="animate-spin" />}
                    Return to engineer
                  </Button>
                  <Button size="sm" variant="ghost" disabled={doing !== null} onClick={() => setSendingBack(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" disabled={busy || doing !== null} onClick={() => call("approve", () => pipelineService.leadReview(ticket.id, { action: "approved", reviewer: person }))}>
                  {doing === "approve" ? <LoaderCircle className="animate-spin" /> : <Check />}
                  Approve closure note
                </Button>
                <Button size="sm" variant="secondary" disabled={doing !== null} onClick={() => setSendingBack(true)}>
                  Return to engineer
                </Button>
              </div>
            )
          ) : (
            <p className="text-xs text-muted-foreground">A lead approves or returns it. Switch to the Lead view to review it.</p>
          )}
        </div>
      ) : needsReview ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
          <Button size="sm" disabled={busy || doing !== null || edited || gap || !saved.trim()} onClick={() => call("submit", () => pipelineService.submitReview(ticket.id, person))}>
            {doing === "submit" ? <LoaderCircle className="animate-spin" /> : <Send />}
            {doing === "submit" ? "Submitting…" : "Submit for lead approval"}
          </Button>
          <span className="text-xs text-muted-foreground">
            {edited ? "Save your changes first." : gap ? "Complete the marked parts first." : `A lead must approve this note before it is sent to ${source}.`}
          </span>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
          <Button size="sm" disabled={blocked || busy || doing !== null || edited || gap || !saved.trim()} onClick={() => call("send", () => pipelineService.closeInJira(ticket.id, person))}>
            {doing === "send" ? <LoaderCircle className="animate-spin" /> : <Send />}
            {doing === "send" ? (fromJira ? "Sending…" : "Closing…") : fromJira ? `Send closure note to ${source}` : `Mark as closed in ${source}`}
          </Button>
          <span className="text-xs text-muted-foreground">
            {why ??
              `${stage === "approved" ? `Approved by ${steps.findLast((s) => s.action === "approved")?.reviewer ?? "the lead"}. ` : ""}${
                fromJira
                  ? `Posts this note on ${ticket.id} and sets the issue to Done. Nothing else is sent to ${source}.`
                  : `Close the ticket in ${source} with this note first. This closes it in the console; nothing is sent to ${source}.`
              }`}
          </span>
        </div>
      )}
      <RequesterEmail
        ticket={ticket}
        ready={edited ? "Save your changes first." : gap || !saved.trim() ? "Save a complete closure note first." : null}
        toJira={toJira}
        source={source}
        onSent={onDone}
      />
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
      <p className="whitespace-pre-wrap break-words px-4 py-3 text-[13px]">{text || "Not provided."}</p>
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
  const role = useViewAs();
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
      .catch((e: unknown) => setRunFailed(e instanceof Error ? e.message : "The agent could not run. Try again."))
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
        title={same ? "No changes since the last run. Edit the ticket, or add a note or reply first." : busy ? "The agents are running. Wait for them to finish." : undefined}
        onClick={() => runAgent(agent)}
      >
        <Play />
        {again ? "Rerun" : "Run"}
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
  const reviewed = ["reviewed", "fix_confirmed", "needs_lead", "in_review", "approved"].includes(ticket?.pipeline_status ?? "");
  const fixing = ticket?.pipeline_status === "reviewed"; // Resolution runs only here
  const confirmed = !closed && ticket?.pipeline_status === "fix_confirmed"; // the closure note is open
  const needsLead = !closed && ticket?.pipeline_status === "needs_lead";
  // The closure note: being written, with the lead, or approved and ready to send.
  const inReview = !closed && ticket?.pipeline_status === "in_review";
  const approved = !closed && ticket?.pipeline_status === "approved";
  const closing = confirmed || inReview || approved;
  const leadSteps = ticket?.lead_reviews ?? [];
  const lastLead = leadSteps.at(-1);
  const approval = leadSteps.findLast((s) => s.action === "approved");
  const fixRuns = ticket?.agent_runs.filter((r) => r.agent === "resolution") ?? [];
  const fixRun = fixRuns.at(-1);
  const answerOf = (run?: AgentRun) => ticket?.fix_outcomes?.findLast((a) => a.agent_run_id === run?.id);
  const fixAnswer = answerOf(fixRun);
  const wrongBefore = fixRuns.slice(0, -1).filter((r) => answerOf(r)?.action === "wrong").length;
  const asking = !closed && (fixing || needsLead) && fixRun !== undefined; // waiting for the engineer's answer
  // A person reviews only a priority Triage lowered; the rest is approved by the agents.
  const autoApproved = decided?.reviewer === "AMS agents (auto)";
  const lowered = recommended !== null && ticket?.reported_priority != null && recommended > ticket.reported_priority;
  const FIX_WORDS: Record<Outcome, string> = { worked: "Fix confirmed", partly: "Resolved with changes", wrong: "Not resolved" };
  const fixStep = (): Partial<FlowStep> =>
    fixAnswer && fixAnswer.action !== "wrong"
      ? { state: "done", summary: FIX_WORDS[fixAnswer.action] }
      : needsLead
        ? { state: "attention", summary: "Escalated to lead", lines: [`${MAX_WRONG} suggested fixes did not resolve the issue`] }
        : asking
          ? { state: "attention", summary: fixAnswer ? "Searching again" : fixRun!.verdict === "resolved" ? "Awaiting your confirmation" : "No matching runbook" }
          : {};
  const noteRun = runOf("closure_quality");
  const noteStep = (): Partial<FlowStep> =>
    inReview
      ? { state: "done", summary: "Awaiting lead approval", lines: [`Submitted by ${lastLead?.reviewer ?? "the engineer"}`] }
      : approved
        ? { state: "attention", summary: jira ? "Ready to send" : "Ready to close", lines: [`Approved by ${approval?.reviewer ?? "the lead"}`, jira ? `Sent to ${source} only when you send it` : "Closed here once you closed it in the source"] }
        : confirmed
      ? {
          state: "attention",
          summary: !noteRun
            ? "Not checked yet"
            : noteRun.verdict === "good"
              ? ticket?.lead_review_required
                ? "Ready to submit"
                : "Ready to send"
              : (LATER_STEP[noteRun.verdict]?.[1] ?? noteRun.verdict),
          lines: [...brief(noteRun), `Sent to ${source} only when you send it`],
        }
      : !["resolved", "closed"].includes(ticket?.status ?? "")
        ? { state: "waiting", summary: "Pending", lines: [WAITS.closure_quality] }
        : {};
  const built: FlowStep[] = ticket
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
          summary: dq ? (DQ_STEP[dq.verdict]?.[1] ?? dq.verdict) : "Pending",
          lines: dq ? [...brief(dq), when(dq.created_at)] : ["Checks the ticket after the next sync, or run it now"],
          run: dq,
          section: "data_quality",
        },
        {
          key: "triage",
          name: "Triage",
          state: recommended !== null ? "done" : triage ? "attention" : "waiting",
          summary: recommended !== null ? `P${recommended} recommended` : triage ? "Inconclusive" : "Pending",
          lines: triage ? [...brief(triage), when(triage.created_at)] : ["Sets the priority after the Data Quality check passes"],
          run: triage,
          section: "triage",
        },
        {
          key: "review",
          name: "Priority review",
          state: reviewed || closed ? "done" : ticket.pipeline_status === "triaged" ? "attention" : "waiting",
          summary: autoApproved
            ? "Not required"
            : reviewed
              ? decided?.final_priority
                ? `P${decided.final_priority} by ${decided.reviewer}`
                : "Priority decided"
              : closed
                ? "Not required"
                : ticket.pipeline_status === "triaged"
                  ? "Awaiting your review"
                  : "Required only if lowered",
          lines: autoApproved
            ? [`Triage did not lower the priority, so P${decided!.final_priority} was approved automatically`]
            : ticket.pipeline_status === "triaged" && lowered
              ? [`Triage lowered the priority from P${ticket.reported_priority} to P${recommended}: accept or change it`]
              : decided?.note
                ? [decided.note]
                : ["Required only when Triage lowers the requester's priority"],
          section: "triage",
        },
        ...(["resolution", "closure_quality", "knowledge_builder"] as const).map(
          (agent): FlowStep => {
            const run = runOf(agent);
            return {
              key: agent,
              name: agent === "knowledge_builder" ? "Knowledge" : AGENTS[agent], // as its card is titled; keeps the bar on one line
              state: run ? (LATER_STEP[run.verdict]?.[0] ?? "attention") : "waiting",
              summary: run ? (LATER_STEP[run.verdict]?.[1] ?? run.verdict) : "Pending",
              lines: run ? [...brief(run), when(run.created_at)] : [WAITS[agent]],
              run,
              section: agent,
              // The fix loop and the closure note, for tickets worked in the console.
              ...(agent === "resolution" ? fixStep() : agent === "closure_quality" ? noteStep() : {}),
            };
          }
        ),
        {
          key: "lead_review",
          name: "Lead review",
          state: !ticket.lead_review_required || approved || closed ? "done" : inReview ? "attention" : "waiting",
          summary: !ticket.lead_review_required
            ? "Not required"
            : approved || (closed && approval)
              ? `Approved by ${approval?.reviewer ?? "the lead"}`
              : inReview
                ? "Awaiting lead approval"
                : lastLead?.action === "sent_back"
                  ? "Returned"
                  : "Pending",
          lines: !ticket.lead_review_required
            ? ["Lead approval applies only when enabled in Settings › Jira"]
            : lastLead?.action === "sent_back" && !inReview && !approved
              ? [`${lastLead.reviewer}: ${lastLead.note ?? ""}`]
              : ["A lead approves the closure note before it is sent to the source"],
          section: "closure_quality",
        },
        {
          key: "back",
          name: jira ? "Close in Jira" : "Close in source",
          state: closed ? "done" : "waiting",
          summary: closed ? "Closed" : "Final step",
          lines: [closed ? `Closed in ${source} ${when(ticket.closed_at)}` : `The closure note is sent to ${source} when you send it`],
          section: null,
        },
      ]
    : [];
  // In the bar's order, so Now is the first unfinished step as the bar shows it; Lead review only where it applies.
  const order = GROUPS.flatMap((g) => g.keys);
  const flow = built
    .filter((s) => s.key !== "lead_review" || ticket?.lead_review_required)
    .sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
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
    if (key === "closure_quality" && (confirmed || approved || ["resolved", "closed"].includes(ticket.status)))
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
            <Run
              run={latestRun}
              action={
                key === "resolution" && !closed && (asking || confirmed) ? (
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
                ) : undefined
              }
            >
              <FeedbackThumbs ticketId={ticket!.id} runId={latestRun.id} agent={latestRun.agent} references={references} given={ratingOf(latestRun)} onSent={load} />
            </Run>
          </ul>
        ) : (
          <p className="px-4 py-3 text-[13px] text-muted-foreground">{key === "triage" ? "Not triaged yet." : (WAITS[key] ?? "Not run yet.")}</p>
        )}
        {key === "resolution" && !closed && (
          <AskAssistant noRunbook={latestRun?.verdict === "no_match"} />
        )}
        {key === "resolution" && references.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">Runbook references</span>
            {references.map((kb) => (
              <RunbookButton key={kb} id={kb} panel />
            ))}
          </div>
        )}
        {key === "triage" && (
          <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
            <p>
              <span className="font-semibold">Priority review: </span>
              {stepOf("review").summary} · {stepOf("review").lines[0]}
            </p>
            {!closed && ticket?.pipeline_status === "triaged" && recommended !== null && (
              <div className="flex flex-wrap items-center gap-2">
                <ReviewActions ticketId={ticket.id} recommended={recommended} onDone={load} />
              </div>
            )}
          </div>
        )}
        {key === "closure_quality" && closing ? (
          <ClosureNote
            key={ticket!.resolution_notes ?? ""}
            ticket={ticket!}
            run={latestRun}
            toJira={jira && writeBack}
            whyNotJira={jira ? "Jira write-back is disabled for this console." : `This ticket did not originate in Jira. Close it in ${source} using this note.`}
            source={source}
            busy={busy}
            onDone={load}
          />
        ) : key === "closure_quality" && latestRun && ticket?.closure_decision?.agent_run_id === latestRun.id ? (
          <div className="flex flex-col gap-2 border-t border-border px-4 py-3 text-[13px]">
            <p className="font-semibold">
              {ticket.closure_decision.action === "accepted"
                ? "Final closure note: agent draft accepted"
                : ticket.closure_decision.action === "edited"
                  ? "Final closure note: your version"
                  : "The check was dismissed; the note is unchanged"}
            </p>
            {ticket.closure_decision.final_text && (
              <p className="whitespace-pre-wrap break-words rounded-lg border border-border bg-muted px-3 py-2 font-mono text-[12px]">{ticket.closure_decision.final_text}</p>
            )}
            <p className="text-xs text-muted-foreground">Stored in the console. Sent to Jira only with the closure note.</p>
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
            <Post label="Post draft reply to Jira" done={ticket!.comments.some((c) => c.body.includes(draft))} onPost={() => pipelineService.replyInJira(ticket!.id, person, draft).then(load)} />
          </div>
        )}
        {older.length > 0 && (
          <Collapsible className="border-t border-border">
            <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-xs font-semibold text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              {key === "resolution" ? "Previous fixes" : "Previous checks"} ({older.length})
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
                          {said ? `${FIX_WORDS[said.action]}${said.note ? `: ${said.note}` : ""} · ${said.reviewer}` : "No response recorded"}
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

  // Is the step bar pinned under the top bar (tablet width and up)? Then it shows in its compact form.
  const barWrap = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(false);
  const loaded = ticket !== null;
  useEffect(() => {
    const el = barWrap.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setPinned(entry.intersectionRatio < 1 && entry.boundingClientRect.top < 80 && window.matchMedia("(min-width: 48rem)").matches),
      { rootMargin: "-71px 0px 0px 0px", threshold: [1] }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loaded]);

  // When a run moves the ticket on, bring the new step into view; not while someone is typing.
  const lastNow = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const key = nowStep?.key ?? null;
    const typing = document.activeElement instanceof HTMLTextAreaElement || document.activeElement instanceof HTMLInputElement;
    if (lastNow.current !== undefined && lastNow.current !== key && key && !typing)
      glideTo(document.getElementById("now"));
    if (ticket) lastNow.current = key;
  }, [nowStep?.key, ticket]);

  // Cards glide to their new place when they move (Now → Recently completed → Coming up / Done) instead of jumping; a card
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
          {/* The step bar: three groups, a popover per step (click or Enter; Esc or outside closes). */}
          {/* From tablet width up it stays under the top bar on a strip of page background, so nothing shows through;
              pinned, it drops the group labels to take less height. On a phone it scrolls away with the page. */}
          <div ref={barWrap} className="md:sticky md:top-[70px] md:z-10 md:-mx-2 md:bg-background md:px-2 md:pt-1 md:pb-2">
          <Card
            className={cn("scroll-thin flex-row flex-nowrap overflow-x-auto transition-[padding,box-shadow] duration-200", pinned ? "py-1 shadow-[0_6px_16px_rgba(25,29,56,0.10)]" : "py-2")}
            aria-label="Workflow progress"
            role="group"
          >
            {GROUPS.map((group) => {
              const steps = group.keys.flatMap((k) => flow.filter((s) => s.key === k));
              const done = steps.filter((s) => s.state === "done").length;
              return (
                <div key={group.label} className="flex shrink-0 flex-auto flex-col gap-1 px-1.5 [&+&]:border-l [&+&]:border-border">
                  <p className={cn("flex items-center gap-1.5 pl-1 font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase", pinned && "sr-only")}>
                    {group.label}
                    <span className={done === steps.length ? "text-p3" : undefined}>{done === steps.length ? "✓ Done" : `${done}/${steps.length}`}</span>
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
                                  {isNow ? "Now" : s.state === "done" ? "Done" : s.state === "attention" ? "Action required" : "Pending"}
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
                                  {stars >= 4 ? <ThumbsUp className="size-3 text-p3" aria-hidden="true" /> : stars <= 2 ? <ThumbsDown className="size-3 text-primary" aria-hidden="true" /> : <Contrast className="size-3" aria-hidden="true" />}
                                  Rated {stars >= 4 ? "correct" : stars <= 2 ? "incorrect" : "partially correct"}
                                </span>
                              )}
                              {(s.section || action) && (
                                <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2">
                                  {s.section && (
                                    <Button size="xs" variant="secondary" onClick={() => openSection(s.section)}>
                                      {s.section === "jira" ? "View description" : "Open section"}
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
          </div>
          {runFailed && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {runFailed}
            </p>
          )}

          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="flex min-w-0 flex-col gap-4">
              <Card id="step-jira" className="scroll-mt-24 gap-0 py-0">
                <SectionHead title="Description" />
                <p className="whitespace-pre-wrap break-words px-4 py-3 text-[13px]">{ticket.description || "Not provided."}</p>
              </Card>

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
                    {nowStep ? nowStep.name : closed ? `Closed in ${source}` : "No action required"}
                  </h2>
                  <span className="text-[13px] text-muted-foreground">
                    {closed
                      ? `No action required. This ticket is closed in ${source}.`
                      : ticket.pipeline_status === "reviewed" && runOf("resolution")
                        ? fixAnswer?.action === "wrong"
                          ? "You reported that the fix did not work. Resolution is searching for another fix using your notes."
                          : "Apply the suggested fix, then confirm whether it resolved the issue. The closure note opens after confirmation."
                        : confirmed && lastLead?.action === "sent_back"
                          ? `${lastLead.reviewer} returned the closure note. Update it, then resubmit it.`
                          : confirmed && ticket.lead_review_required
                            ? "Fix confirmed. Complete the closure note, then submit it for lead approval."
                            : (NEXT[ticket.pipeline_status] ?? ticket.pipeline_status)}
                  </span>
                  {nowStep && actionFor(nowStep.key) && <span className="ml-auto">{actionFor(nowStep.key)}</span>}
                </div>
                {busy && (
                  <p role="status" className="flex items-center gap-2 text-[13px] font-medium text-primary">
                    <LoaderCircle className="size-3.5 animate-spin" />
                    {working ? WORKING[working] : "The agents are running. This page updates automatically."}
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
                    Recently completed
                  </h2>
                  {card(freshShown)}
                </section>
              )}

              {cardsNext.length > 0 && (
                <section aria-labelledby="next-h" className="flex flex-col gap-2">
                  <h2 id="next-h" className="pl-1 font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">
                    {closed ? "Needs attention" : "Up next"}
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
                    ? "This ticket did not originate in Jira, so replies to the requester can't be sent from here."
                    : closed
                      ? `The ticket is closed in ${source}.`
                      : "Jira write-back is disabled for this console."
                }
                onSent={load}
              />
            </div>

            <div className="flex flex-col gap-4">
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
                    ["Recommended priority", recommended !== null ? <PriorityChip priority={recommended} /> : "Not triaged yet"],
                    ...(decided
                      ? [
                          [
                            "Confirmed priority",
                            <span key="d" className="inline-flex flex-wrap items-center gap-2">
                              <PriorityChip priority={decided.final_priority} />
                              {[`by ${decided.reviewer}`, decided.note].filter(Boolean).join(" · ")}
                            </span>,
                          ] as [string, React.ReactNode],
                        ]
                      : []),
                    [
                      "Requested priority",
                      ticket.reported_priority ? (
                        <span className="inline-flex items-center gap-2">
                          <PriorityChip priority={ticket.reported_priority} />
                          {ticket.reported_priority_label}
                        </span>
                      ) : (
                        "—"
                      ),
                    ],
                    ["Requester", /^<[A-Z_]+_\d+>$/.test(ticket.reporter_name ?? "") ? "Name masked" : (ticket.reporter_name ?? "—")],
                    [
                      "Assigned to",
                      role !== "engineer" && !closed ? (
                        <span className="inline-flex flex-wrap items-center gap-2">
                          {ticket.assignment_group}
                          <AssignControl ticketId={ticket.id} assignee={ticket.assignee} onDone={load} />
                        </span>
                      ) : (
                        [ticket.assignment_group, ticket.assignee].filter(Boolean).join(" · ") || "—"
                      ),
                    ],
                    ["Opened", when(ticket.opened_at)],
                    ...(closed ? ([["Closed", when(ticket.closed_at)]] as [string, React.ReactNode][]) : []),
                    ["Source status", (ticket.source_status ?? ticket.status).replace(/^[a-z]/, (c) => c.toUpperCase()).replace(/_/g, " ")],
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
              This ticket was imported from a ServiceNow sheet. The agents have not processed it: only tickets synced from Jira currently go through Data Quality
              and Triage.
            </AlertDescription>
          </Alert>
          <Card className="gap-0 py-0">
            <SectionHead title="Ticket" />
            <Facts
              rows={[
                ["Priority", <PriorityChip key="p" priority={sheet.priority} />],
                ["Requester", sheet.caller ?? "—"],
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
      {ticket && !closed && <FixChat
          ticket={ticket}
          noRunbook={runOf("resolution")?.verdict === "no_match"}
          renderRun={(run) => (
            <ul role="list">
              <Run run={run} />
            </ul>
          )}
          onDone={load}
        />}
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
