"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import { FeedbackStars } from "@/components/console/feedback-stars";
import { ReviewActions } from "@/components/console/review-actions";
import { SectionHead, SlaClock } from "@/components/console/sync-parts";
import { STAGES } from "@/components/console/dashboard";
import { humanize } from "@/components/console/document-hints";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api-client";
import { usePerson } from "@/lib/view-as";
import { incidentService } from "@/services/incident-service";
import { jiraService } from "@/services/jira-service";
import { pipelineService } from "@/services/pipeline-service";
import { ticketService } from "@/services/ticket-service";
import { AttentionItem } from "@/types/incident";
import { AgentRun, FLAGS, PipelineTicket } from "@/types/pipeline";
import { ServiceNowTicket } from "@/types/servicenow";
import { Check, LoaderCircle, Play, Send, Star, TriangleAlert } from "lucide-react";
import { cn } from "cn";

const STAGE_WORDS: Record<string, string> = { ...Object.fromEntries(STAGES), historical: "Closed before the agents started" };
const AGENTS: Record<string, string> = {
  data_quality: "Data Quality",
  triage: "Triage",
  resolution: "Resolution",
  closure_quality: "Closure Quality",
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
};

/** What the person looking at the ticket has to do, by stage. */
const NEXT: Record<string, string> = {
  pending: "Nothing yet. The Data Quality agent checks this ticket after the next Jira sync, or run it now.",
  awaiting_info: "Ask the reporter for the missing details. The agent drafted the reply.",
  dq_passed: "Nothing yet. The Triage agent sets a priority next, or run it now.",
  triaged: "Review the recommended priority: agree with it or change it.",
  reviewed: "The priority is decided. The Resolution agent looks for the fix on the next sync; then work the ticket in Jira.",
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
// Resolution and Closure Quality: the words under their step, by verdict.
const LATER_STEP: Record<string, ["done" | "attention", string]> = {
  resolved: ["done", "Fix found"],
  no_match: ["attention", "No runbook covers it"],
  good: ["done", "Close notes good"],
  needs_work: ["attention", "Close notes need work"],
  not_applicable: ["done", "Not needed"],
  uncertain: ["attention", "Could not decide"],
};
const STEP_ICONS = { done: Check, attention: TriangleAlert, waiting: null };
// Stages where a person may start the agents; the server refuses the rest.
const CAN_RUN = ["pending", "awaiting_info", "dq_passed", "triaged", "error"];
type Agent = "data_quality" | "triage" | "resolution" | "closure_quality";

const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
const show = (v: unknown) => (Array.isArray(v) ? v.join(", ") || "none" : v === null || v === "" ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : String(v));

function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <Table>
      <TableBody>
        {rows.map(([k, v]) => (
          <TableRow key={k}>
            <TableHead scope="row" className="w-40 px-4 text-[13px] font-normal">
              {k}
            </TableHead>
            <TableCell>{v}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** One stop on the agents' track: a node joined to the next by a line that fills once the step is done. */
function Step({
  n,
  state,
  name,
  running,
  action,
  rating,
  children,
}: {
  n: number;
  state: keyof typeof STEP_ICONS;
  name: string;
  running?: boolean;
  action?: React.ReactNode;
  /** Stars a person gave this step's result. */
  rating?: number;
  children: React.ReactNode;
}) {
  const Icon = running ? LoaderCircle : STEP_ICONS[state];
  return (
    <li className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center" aria-hidden="true">
        <span
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums",
            running
              ? "border-primary text-primary"
              : state === "done"
                ? "border-foreground bg-foreground text-background"
                : state === "attention"
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border-strong text-muted-foreground"
          )}
        >
          {Icon ? <Icon className={cn("size-4", running && "animate-spin")} /> : n}
        </span>
        {n < 5 && <span className={cn("h-0.5 flex-1", state === "done" && !running ? "bg-foreground" : "bg-border")} />}
      </div>
      <div className="flex min-w-0 flex-col items-start gap-1 pr-3">
        <span className="text-xs text-muted-foreground">{name}</span>
        <span className="inline-flex flex-wrap items-center gap-1.5 text-[13px] font-medium">{running ? "Running…" : children}</span>
        {rating !== undefined && !running && (
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Star className="size-3 fill-current text-primary" aria-hidden="true" />
            Rated {rating} of 5
          </span>
        )}
        {action}
      </div>
    </li>
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
              <span className="font-semibold">Ranked higher from engineers' ratings: </span>
              <span className="font-mono">{higher.join(", ")}</span>
            </span>
          )}
          {lower.length > 0 && (
            <span>
              <span className="font-semibold">Ranked lower from engineers' ratings: </span>
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
function Note({ ticketId, text, busy, rerun, onSaved }: { ticketId: string; text: string; busy: boolean; rerun?: () => void; onSaved: () => unknown }) {
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
    <div className="flex flex-col gap-2 border-b border-border px-4 py-3 text-[13px]">
      <label htmlFor="note" className="font-semibold">
        Tell the agents more
      </label>
      <Textarea id="note" rows={3} maxLength={4000} value={value} onChange={(e) => setValue(e.target.value)} aria-describedby="note-help" />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" disabled={saving || value.trim() === text} onClick={() => save(onSaved)}>
          {saving ? "Saving…" : "Save note"}
        </Button>
        {rerun && (
          <Button size="sm" disabled={saving || busy} onClick={() => save(rerun)}>
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

  const load = useCallback(
    () =>
      pipelineService
        .getTicket(id)
        .then(setTicket)
        .catch((e: unknown) => {
          if (!(e instanceof ApiError) || e.status !== 404) throw e;
          return ticketService.getTicket(id).then(setSheet);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : `Couldn't load ${id}`)),
    [id]
  );

  useEffect(() => {
    load();
  }, [load]);

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
  const runButton = (agent: Agent, again: boolean) => (
    <Button size="xs" variant="secondary" disabled={running !== null} onClick={() => runAgent(agent)}>
      <Play />
      {again ? "Run again" : "Run"}
    </Button>
  );

  const triage = ticket?.agent_runs.findLast((r) => r.agent === "triage");
  const dq = ticket?.agent_runs.findLast((r) => r.agent === "data_quality");
  const latest = [dq, triage, ...["resolution", "closure_quality"].map((a) => ticket?.agent_runs.findLast((r) => r.agent === a))].filter(
    (r) => r !== undefined,
  );
  const earlier = ticket?.agent_runs.filter((r) => !latest.includes(r)) ?? [];
  // The draft reply can go to Jira only while the ticket still waits for the reporter, and only from the latest check.
  const draft = ticket?.pipeline_status === "awaiting_info" ? (dq?.output.answer as { chase_email?: string | null } | undefined)?.chase_email : null;
  const recommended = typeof triage?.output.priority === "number" ? triage.output.priority : null;
  const decided = ticket?.decided?.final_priority ? ticket.decided : null;
  // A result's rating: this person's latest, else the latest anyone gave.
  const ratingOf = (run?: AgentRun) => {
    const given = (ticket?.feedback ?? []).filter((f) => f.agent_run_id === run?.id);
    return given.findLast((f) => f.reviewer === person) ?? given.at(-1);
  };
  const rerun =
    !closed && ticket?.pipeline_status === "reviewed" ? () => runAgent("resolution") : canRun ? () => runAgent("data_quality") : undefined;
  const back = (
    <Button variant="secondary" nativeButton={false} render={<Link href="/tickets" />}>
      All tickets
    </Button>
  );

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
          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <Card className="gap-0 py-0">
              <SectionHead title="Where it stands" />
              <Facts
                rows={[
                  ["Stage", closed ? `Closed in ${source}` : (STAGE_WORDS[ticket.pipeline_status] ?? ticket.pipeline_status)],
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
                  ...(sla && !closed
                    ? ([["SLA", <SlaClock key="sla" state={sla.state} minutesLeft={sla.minutes_left} usedPercent={sla.used_percent} />]] as [
                        string,
                        React.ReactNode,
                      ][])
                    : []),
                  ["Status in the source", ticket.source_status ?? ticket.status],
                ]}
              />
            </Card>

            <Card className="gap-0 py-0">
              <SectionHead title="What the agents decided">
                {jira && writeBack && !closed && latest.length > 0 && (
                  <Post label="Post the summary to Jira" onPost={() => pipelineService.sendToJira(ticket.id, person).then(load)} />
                )}
              </SectionHead>
              <ol role="list" className="grid grid-cols-5 border-b border-border px-4 py-4">
                <Step
                  n={1}
                  state={dq ? (DQ_STEP[dq.verdict]?.[0] ?? "attention") : "waiting"}
                  name="Data Quality"
                  running={running === "data_quality"}
                  action={canRun && runButton("data_quality", dq !== undefined)}
                  rating={ratingOf(dq)?.stars}
                >
                  {dq ? (DQ_STEP[dq.verdict]?.[1] ?? dq.verdict) : "Not yet"}
                </Step>
                <Step
                  n={2}
                  state={recommended !== null ? "done" : triage ? "attention" : "waiting"}
                  name="Triage"
                  running={running === "triage"}
                  action={canRun && ["dq_passed", "triaged"].includes(ticket.pipeline_status) && runButton("triage", triage !== undefined)}
                  rating={ratingOf(triage)?.stars}
                >
                  {recommended !== null ? (
                    <>
                      <PriorityChip priority={recommended} /> recommended
                    </>
                  ) : triage ? (
                    "Could not decide"
                  ) : (
                    "Not yet"
                  )}
                </Step>
                <Step
                  n={3}
                  state={ticket.pipeline_status === "reviewed" ? "done" : ticket.pipeline_status === "triaged" && !closed ? "attention" : "waiting"}
                  name="Review by a person"
                >
                  {ticket.pipeline_status === "reviewed" ? (
                    decided ? (
                      <span className="inline-flex items-center gap-2">
                        <PriorityChip priority={decided.final_priority} /> decided by {decided.reviewer}
                      </span>
                    ) : (
                      "Priority decided"
                    )
                  ) : closed ? "Not needed" : ticket.pipeline_status === "triaged" ? "Waiting for you" : "Not yet"}
                </Step>
                {(["resolution", "closure_quality"] as const).map((agent, i) => {
                  const run = ticket.agent_runs.findLast((r) => r.agent === agent);
                  // The server takes Resolution on reviewed tickets and Closure Quality on resolved ones.
                  const ready = agent === "resolution" ? !closed && ticket.pipeline_status === "reviewed" : ["resolved", "closed"].includes(ticket.status);
                  return (
                    <Step
                      key={agent}
                      n={4 + i}
                      state={run ? (LATER_STEP[run.verdict]?.[0] ?? "attention") : "waiting"}
                      name={AGENTS[agent]}
                      running={running === agent}
                      action={ready && runButton(agent, run !== undefined)}
                      rating={ratingOf(run)?.stars}
                    >
                      {run ? (LATER_STEP[run.verdict]?.[1] ?? run.verdict) : "Not yet"}
                    </Step>
                  );
                })}
              </ol>
              <div className="flex flex-col gap-2 border-b border-border bg-muted px-4 py-3 text-[13px]">
                <p>
                  <span className="font-semibold">What to do next: </span>
                  {closed
                    ? `Nothing. This ticket is closed in ${source}.`
                    : ticket.pipeline_status === "reviewed" && jira && writeBack
                      ? NEXT.reviewed.replace("decided.", "decided and set on the Jira issue.")
                      : (NEXT[ticket.pipeline_status] ?? ticket.pipeline_status)}
                </p>
                {runFailed && (
                  <p role="alert" className="text-xs font-medium text-destructive">
                    {runFailed}
                  </p>
                )}
                {!closed && ticket.pipeline_status === "triaged" && recommended !== null && (
                  <div className="flex flex-wrap items-center gap-2">
                    <ReviewActions ticketId={ticket.id} recommended={recommended} onDone={load} />
                  </div>
                )}
                {draft && writeBack && !closed && (
                  <Post
                    label="Post the draft reply to Jira"
                    done={ticket.comments.some((c) => c.body.includes(draft))}
                    onPost={() => pipelineService.replyInJira(ticket.id, person, draft).then(load)}
                  />
                )}
              </div>
              {!closed && (
                // After the decision, not before it. Remounts when the stored note changes, so the box shows it as kept (personal details masked).
                <Note key={ticket.guidance ?? ""} ticketId={ticket.id} text={ticket.guidance ?? ""} busy={running !== null} rerun={rerun} onSaved={load} />
              )}
              {latest.length ? (
                <ul role="list">
                  {latest.map((r) => (
                    <Run key={r.id} run={r}>
                      <FeedbackStars ticketId={ticket.id} runId={r.id} given={ratingOf(r)} onSent={load} />
                    </Run>
                  ))}
                </ul>
              ) : (
                <p className="px-4 py-3 text-[13px] text-muted-foreground">No agent has checked this ticket yet.</p>
              )}
              {earlier.length > 0 && (
                <details className="border-t border-border">
                  <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-primary">Earlier checks ({earlier.length})</summary>
                  <ul role="list" className="border-t border-border">
                    {earlier.map((r) => (
                      <Run key={r.id} run={r} />
                    ))}
                  </ul>
                </details>
              )}
            </Card>
          </div>

          <Text title="Description" text={ticket.description} />

          {ticket.comments.length > 0 && (
            <Card className="gap-0 py-0">
              <SectionHead title="Replies" />
              <ul role="list">
                {ticket.comments.map((c) => (
                  <li key={c.id} className="flex flex-col gap-1 border-b border-border px-4 py-3 text-[13px] last:border-b-0">
                    <span className="text-xs text-muted-foreground">
                      {/^<[A-Z_]+_\d+>$/.test(c.author_email) ? "Reporter" : c.author_email} · {c.from_reporter ? "reporter" : "support"} ·{" "}
                      {when(c.created_at)}
                    </span>
                    <p className="whitespace-pre-wrap break-words">{c.body}</p>
                  </li>
                ))}
              </ul>
            </Card>
          )}
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
        <Ticket />
      </Suspense>
    </AppShell>
  );
}
