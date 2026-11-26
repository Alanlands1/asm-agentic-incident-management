"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { Check } from "lucide-react";
import { AppShell } from "@/components/console/app-shell";
import { CountUp } from "@/components/console/count-up";
import { ListRow } from "@/components/console/list-row";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import { RunbookButton } from "@/components/console/runbook-button";
import {
  ActivityCard, BoardTicket, STATUSES, Sla, StagePill, Task, and, appOf, count, nextStep, tasksOf, ticketHref, useBoard,
} from "@/components/console/persona-parts";
import { SectionHead, SlaGauge, Status, dueWords, span } from "@/components/console/sync-parts";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiClient } from "@/lib/api-client";
import { usePerson, useViewAs } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { cn } from "cn";

const TILE = "h-auto min-w-32 flex-1 basis-32 flex-col items-start gap-0 whitespace-normal rounded-[14px] px-4 py-2.5 text-left";
type Closed = { id: string; summary: string | null; at: string; kb: string | null };

const never = () => () => {};
const thisHour = () => new Date().setMinutes(0, 0, 0);

/** Each agent's result on the ticket, in order, as small labels (design canvas). */
function Chain({ ticket }: { ticket: BoardTicket }) {
  const links = [
    ticket.dq_verdict && `Data Quality · ${ticket.dq_verdict === "passed" ? "passed" : ticket.dq_verdict === "needs_info" ? "needs information" : ticket.dq_verdict}`,
    ticket.priority && `Triage · P${ticket.priority}`,
    ticket.fix_verdict &&
      `Resolution · ${ticket.fix_answer === "worked" || ticket.fix_answer === "partly" ? "fix applied" : ticket.fix_answer === "wrong" ? "fix did not work" : ticket.fix_verdict === "resolved" ? "fix suggested" : "no runbook fix"}`,
    ticket.closure_verdict && `Closure Quality · ${ticket.closure_score != null ? `${ticket.closure_score} of 6` : ticket.closure_verdict}`,
    ticket.lead_step && `Lead · ${ticket.lead_step === "sent_back" ? "returned" : ticket.lead_step}`,
  ].filter((l): l is string => !!l);
  if (links.length === 0) return null;
  return (
    <ol role="list" aria-label="Agent results" className="flex flex-wrap gap-1.5">
      {links.map((l) => (
        <li key={l}>
          <Badge variant="secondary">
            <Check aria-hidden="true" />
            {l}
          </Badge>
        </li>
      ))}
    </ol>
  );
}

/** The next action on the hero ticket, as a sentence. */
function nextSentence(t: BoardTicket) {
  if (t.stage === "fix_confirmed" && t.lead_step === "sent_back") return `${t.lead_by ?? "The lead"} returned your closure note. Update it, then resubmit it.`;
  if (t.stage === "fix_confirmed")
    return `${t.closure_score != null ? `Closure Quality score: ${t.closure_score} of 6. ` : ""}${t.review_required ? "Complete it, then submit it for lead approval." : "Complete it, then send it."}`;
  if (t.stage === "approved") return `${t.lead_by ?? "The lead"} approved the closure note. Close the ticket with it.`;
  if (t.stage === "in_review") return "The closure note is awaiting lead approval.";
  if (t.stage === "reviewed" && t.fix_verdict === "resolved" && t.fix_answer !== "wrong") return "Apply the suggested fix, then confirm the outcome.";
  if (t.stage === "reviewed" && t.fix_verdict && t.fix_answer !== "wrong")
    return "No runbook covers this issue. Resolve it, then record how: that drafts the closure note.";
  return `${nextStep(t)}.`;
}

/** My worklist (design canvas): the viewer's tickets, what to do now, their tasks and what they closed this week. */
export function MyWorklist() {
  const viewer = usePerson();
  const role = useViewAs();
  const lead = role === "lead" || role === "admin";
  const { board, error } = useBoard(viewer);
  const [status, setStatus] = useState<string | null>(null);
  const [closed, setClosed] = useState<Closed[] | null>(null);
  const [toReview, setToReview] = useState<{ id: string; summary: string }[]>([]);
  const hour = useSyncExternalStore(never, thisHour, () => null);
  const now = hour === null ? null : new Date(hour);

  useEffect(() => {
    if (!viewer) return; // who is signed in is not known yet
    apiClient<Closed[]>(`/personas/closed?person=${encodeURIComponent(viewer)}&days=7`).then(setClosed, () => setClosed([]));
    if (lead) pipelineService.listByStage("in_review").then((r) => setToReview(r.items), () => setToReview([]));
  }, [viewer, lead, board]);

  const t = board?.totals;
  const tickets = board?.tickets ?? [];
  const hero = tickets.find((x) => !["awaiting_info", "in_review", "pending", "dq_passed"].includes(x.stage));
  const chosen = STATUSES.find((s) => s.key === status);
  const listed = (chosen ? tickets.filter((x) => chosen.stages.includes(x.stage)) : tickets.filter((x) => x !== hero)).sort(
    (a, b) => (a.priority ?? 9) - (b.priority ?? 9) || (a.minutes_left ?? Infinity) - (b.minutes_left ?? Infinity)
  );
  const tasks: Task[] = [
    ...(lead ? toReview : []).map((x) => ({ key: `review ${x.id}`, ticket: x.id, what: `Review closure note on ${x.id}`, from: x.summary })),
    ...tasksOf(tickets),
  ];
  const wrong = [
    t?.sla_breached && `${count(t.sla_breached, "ticket has", "tickets have")} breached SLA`,
    t?.sla_at_risk && `${count(t.sla_at_risk, "ticket is", "tickets are")} near breach`,
  ].filter((part): part is string => !!part);
  const nearest = tickets.reduce<BoardTicket | null>((f, x) => (x.minutes_left !== null && (!f || x.minutes_left < f.minutes_left!) ? x : f), null);

  return (
    <AppShell>
      <PageHeader
        title={now ? `Good ${now.getHours() < 12 ? "morning" : now.getHours() < 18 ? "afternoon" : "evening"}, ${viewer.split(" ")[0]}` : " "}
        context={
          !t || !now ? (
            error ? undefined : <Skeleton className="mt-1 h-3.5 w-72 max-w-full" />
          ) : (
            `My worklist · ${now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })} · ${count(t.open, "open ticket", "open tickets")} assigned to you`
          )
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {t && (
        <p role="status" className="text-[13px]">
          <Status ok={wrong.length === 0}>
            <span>
              <span className="font-semibold">{wrong.length ? `${and.format(wrong)}.` : "No SLA breaches."}</span>
              {nearest &&
                (nearest.minutes_left! < 0
                  ? ` The most overdue is ${span(nearest.minutes_left!)} over.`
                  : ` The nearest deadline is ${nearest.due_at ? dueWords(nearest.due_at) : `in ${span(nearest.minutes_left!)}`}.`)}
            </span>
          </Status>
        </p>
      )}

      {hero && (
        <Card className="gap-4 px-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <p className="text-xs font-medium text-muted-foreground">Start here</p>
            <h2 className="flex flex-wrap items-center gap-2 text-base font-semibold">
              <PriorityChip priority={hero.priority} />
              {hero.summary || "No summary"}
            </h2>
            <p className="text-xs text-muted-foreground">
              <span className="font-mono">{hero.id}</span> · {appOf(hero)}
            </p>
            <p className="text-sm">{nextSentence(hero)}</p>
            <Chain ticket={hero} />
            <div className="flex flex-wrap gap-2 pt-1">
              <Button nativeButton={false} render={<Link href={ticketHref(hero)} />}>
                Open ticket
              </Button>
              {hero.runbook && <RunbookButton id={hero.runbook} label={`Open runbook ${hero.runbook}`} />}
            </div>
          </div>
          {hero.minutes_left !== null && hero.used_percent !== null ? (
            <div className="flex shrink-0 flex-col items-center rounded-[14px] bg-primary p-4 text-primary-foreground">
              <SlaGauge minutesLeft={hero.minutes_left} usedPercent={hero.used_percent} dueAt={hero.due_at} />
            </div>
          ) : (
            <div className="flex shrink-0 flex-col gap-2 rounded-[14px] border border-border p-3">
              <p className="text-xs font-medium text-muted-foreground">SLA</p>
              <Sla ticket={hero} />
            </div>
          )}
        </Card>
      )}

      <section aria-label="My tickets by status" className="flex flex-wrap gap-2">
        {STATUSES.map((s) => {
          const n = tickets.filter((x) => s.stages.includes(x.stage)).length;
          return (
            <Button key={s.key} variant="secondary" aria-pressed={status === s.key} onClick={() => setStatus(status === s.key ? null : s.key)} className={cn(TILE, status === s.key && "border-2 border-foreground")}>
              <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] uppercase">{s.label}</span>
              <span className="text-2xl leading-8 tabular-nums">{board ? <CountUp value={n} /> : "—"}</span>
              <span className="text-xs font-normal text-muted-foreground">{s.sub}</span>
            </Button>
          );
        })}
      </section>

      <div className="grid items-start gap-4 lg:grid-cols-3">
        <Card className="gap-0 py-0 lg:col-span-2">
          <SectionHead title={`${chosen ? chosen.label : "Up next"} · ${listed.length}`}>
            <span className="text-xs text-muted-foreground">Sorted by priority, then nearest deadline</span>
          </SectionHead>
          {!board ? (
            <div className="flex flex-col gap-3 px-4 py-3">{error ? null : Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-5" />)}</div>
          ) : listed.length === 0 ? (
            <p className="px-4 py-6 text-muted-foreground">{tickets.length ? "No tickets." : `No open tickets are assigned to ${viewer}.`}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Priority</TableHead>
                  <TableHead>Ticket</TableHead>
                  <TableHead className="hidden sm:table-cell">Stage</TableHead>
                  <TableHead className="hidden md:table-cell">SLA</TableHead>
                  <TableHead className="pr-4 text-right">Next step</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {listed.map((x) => (
                  <TableRow key={x.id}>
                    <TableCell className="pl-4">
                      <PriorityChip priority={x.priority} />
                    </TableCell>
                    <TableCell className="min-w-48 whitespace-normal">
                      <Link href={ticketHref(x)} className="font-medium underline-offset-4 hover:underline">
                        {x.summary || "No summary"}
                      </Link>
                      <span className="block text-xs text-muted-foreground">
                        <span className="font-mono">{x.id}</span> · {appOf(x)}
                      </span>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <StagePill ticket={x} />
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <Sla ticket={x} />
                    </TableCell>
                    <TableCell className="pr-4">
                      <div className="flex items-center justify-end gap-3">
                        <span className="hidden w-36 shrink-0 text-right text-xs whitespace-normal text-muted-foreground 2xl:inline">{nextStep(x)}</span>
                        <Button variant="secondary" size="sm" nativeButton={false} render={<Link href={ticketHref(x)} />}>
                          Open
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>

        <div className="flex flex-col gap-4">
          <Card className="gap-0 py-0">
            <SectionHead title={`My tasks · ${tasks.length}`} />
            {tasks.length === 0 ? (
              <p className="px-4 py-3 text-[13px] text-muted-foreground">{board ? "No pending tasks." : "Loading…"}</p>
            ) : (
              <ul role="list">
                {tasks.map((task) => (
                  <ListRow
                    key={task.key}
                    title={
                      <Link href={`/tickets/${encodeURIComponent(task.ticket)}`} className="underline-offset-4 hover:underline">
                        {task.what}
                      </Link>
                    }
                    meta={task.from}
                  />
                ))}
              </ul>
            )}
          </Card>

          <Card className="gap-0 py-0">
            <SectionHead title="Closed by you this week" />
            {!closed || closed.length === 0 ? (
              <p className="px-4 py-3 text-[13px] text-muted-foreground">{closed ? "No tickets closed this week." : "Loading…"}</p>
            ) : (
              <ul role="list">
                {closed.map((c) => (
                  <ListRow
                    key={c.id}
                    itemKey={c.id}
                    title={
                      <Link href={`/tickets/${encodeURIComponent(c.id)}`} className="underline-offset-4 hover:underline">
                        {c.summary || "No summary"}
                      </Link>
                    }
                    trailing={<Badge variant="secondary" className={cn(c.kb && "border-p3 text-p3")}>{c.kb === "draft" ? "KB draft" : c.kb ? `KB ${c.kb}` : "Note sent"}</Badge>}
                  />
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {board && <ActivityCard title="Activity on your tickets · today" person={viewer} asOf={board} />}
    </AppShell>
  );
}
