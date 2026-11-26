"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { AppShell } from "@/components/console/app-shell";
import { AssignControl } from "@/components/console/assign-control";
import { ListRow } from "@/components/console/list-row";
import { PageHeader } from "@/components/console/page-header";
import { MajorIncidents, atRisk } from "@/components/console/persona-overview";
import { ActivityCard, Board, BoardTicket, NO_ENGINEER, StagePill, ageOf, and, appOf, count, ticketHref, useBoard } from "@/components/console/persona-parts";
import { PriorityChip } from "@/components/console/priority-chip";
import { StatTile } from "@/components/console/stat-tile";
import { SectionHead, span } from "@/components/console/sync-parts";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePerson } from "@/lib/view-as";
import { incidentService } from "@/services/incident-service";
import { pipelineService } from "@/services/pipeline-service";
import { Attention } from "@/types/incident";
import { cn } from "cn";

const never = () => () => {};
const thisMinute = () => Math.floor(Date.now() / 60000) * 60000;

const slaWords = (t: BoardTicket) => (t.minutes_left === null ? null : `SLA ${span(t.minutes_left)} ${t.minutes_left < 0 ? "over" : "left"}`);
// With the lead: three fixes did not work, or a closure note waits for approval.
const withLead = (t: BoardTicket) => t.stage === "needs_lead" || t.stage === "in_review";

/** One ticket in a list of the desk: priority, id and summary, a line of facts, and the lead's action on it. */
function TicketRow({
  ticket,
  facts,
  note,
  actions,
}: {
  ticket: BoardTicket;
  facts: (string | null | false | undefined)[];
  /** A second line of facts, e.g. who is suggested and why. */
  note?: string | false;
  actions: React.ReactNode;
}) {
  const sla = atRisk(ticket) && slaWords(ticket);
  return (
    <ListRow
      lead={<PriorityChip priority={ticket.priority} />}
      itemKey={ticket.id}
      title={
        <Link href={ticketHref(ticket)} className="underline-offset-4 hover:underline">
          {ticket.summary || "No summary"}
        </Link>
      }
      meta={
        <>
          <span>{facts.filter(Boolean).join(" · ")}</span>
          {sla && <span className="font-semibold text-critical tabular-nums">{sla}</span>}
          {note && <span className="basis-full text-foreground">{note}</span>}
        </>
      }
      actions={actions}
    />
  );
}

const FIRST = 5;

/** One of the lead's four lists, the first five until asked for all. Empty, it says so in a line. */
function Section({
  id,
  title,
  empty,
  tickets,
  action,
  children,
}: {
  id: string;
  title: string;
  empty: string;
  tickets: BoardTicket[] | null;
  action?: React.ReactNode;
  children: (t: BoardTicket) => React.ReactNode;
}) {
  const [all, setAll] = useState(false);
  return (
    <Card id={id} className="scroll-mt-24 gap-0 py-0">
      <SectionHead title={tickets ? `${title} · ${tickets.length}` : title}>{action}</SectionHead>
      {!tickets ? (
        <div className="flex flex-col gap-3 px-4 py-3">
          <Skeleton className="h-5" />
          <Skeleton className="h-5" />
        </div>
      ) : tickets.length === 0 ? (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">{empty}</p>
      ) : (
        <ul role="list">{(all ? tickets : tickets.slice(0, FIRST)).map(children)}</ul>
      )}
      {tickets && tickets.length > FIRST && (
        <div className="border-t border-border px-4 py-2">
          <Button size="xs" variant="ghost" onClick={() => setAll(!all)}>
            {all ? `Show first ${FIRST}` : `Show all (${tickets.length})`}
          </Button>
        </div>
      )}
    </Card>
  );
}

type Suggestion = { id: string; name: string; reason: string };

/** Every suggested engineer in one go, after the lead has seen who gets how many. Failures are listed by ticket. */
function AssignSuggested({ suggestions, onDone }: { suggestions: Suggestion[]; onDone: () => unknown }) {
  const by = usePerson();
  const [open, setOpen] = useState(false);
  const [progress, setProgress] = useState<number | null>(null); // tickets tried so far, while it runs
  const [result, setResult] = useState<{ assigned: number; failed: string[] } | null>(null);
  const shares = [...suggestions.reduce((c, s) => c.set(s.name, (c.get(s.name) ?? 0) + 1), new Map<string, number>())];

  const run = async () => {
    const failed: string[] = [];
    for (const [i, s] of suggestions.entries()) {
      setProgress(i);
      try {
        await pipelineService.assign(s.id, s.name, by);
      } catch (e) {
        failed.push(`${s.id}: ${e instanceof Error ? e.message : "not assigned"}`);
      }
    }
    setProgress(null);
    setResult({ assigned: suggestions.length - failed.length, failed });
  };
  const close = (next: boolean) => {
    if (progress !== null) return; // not while it runs
    setOpen(next);
    if (!next && result) {
      setResult(null);
      onDone();
    }
  };

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Assign all suggested
      </Button>
      <Dialog open={open} onOpenChange={close}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{result ? `${count(result.assigned, "ticket", "tickets")} assigned` : `Assign ${count(suggestions.length, "ticket", "tickets")}?`}</DialogTitle>
            <DialogDescription>
              {result
                ? result.failed.length
                  ? `${count(result.failed.length, "ticket was", "tickets were")} not assigned.`
                  : "Each engineer now has the tickets suggested for them."
                : `${and.format(shares.map(([name, n]) => `${name} gets ${n}`))}. A Jira issue is assigned in Jira too.`}
            </DialogDescription>
          </DialogHeader>
          {result && result.failed.length > 0 && (
            <ul role="list" className="flex max-h-40 flex-col gap-1 overflow-y-auto text-sm text-critical">
              {result.failed.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
          <DialogFooter>
            {result ? (
              <Button onClick={() => close(false)}>Close</Button>
            ) : (
              <>
                <Button variant="secondary" onClick={() => close(false)} disabled={progress !== null}>
                  Cancel
                </Button>
                <Button onClick={run} disabled={progress !== null}>
                  {progress !== null ? `Assigning ${progress + 1} of ${suggestions.length}…` : "Assign all"}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** "Off shift", or "On leave until 27 Nov". */
export const stateWords = (s: { state: string; until: string | null }) =>
  s.state === "on_leave"
    ? `On leave${s.until ? ` until ${new Date(`${s.until}T00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}`
    : s.state === "off_shift"
      ? "Off shift"
      : "On shift";

/** Who has what: one line per engineer; pressing a name lists their tickets, each with a way to give it to someone else. */
export function Workload({ board, onChange }: { board: Board; onChange: () => unknown }) {
  const [open, setOpen] = useState<string | null>(null); // the engineer's name; "" is nobody
  const [working, setWorking] = useState<Awaited<ReturnType<typeof pipelineService.availability>>>({});
  useEffect(() => {
    pipelineService.availability().then(setWorking, () => setWorking({}));
  }, [board]);
  return (
    <Card className="gap-0 py-0">
      <SectionHead title="Workload by engineer">
        <Button size="sm" variant="secondary" nativeButton={false} render={<Link href="/lead/team" />}>
          Hours and leave
        </Button>
      </SectionHead>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="pl-4">Engineer</TableHead>
            <TableHead className="text-right">Open</TableHead>
            <TableHead className="text-right">P1 and P2</TableHead>
            <TableHead className="text-right">SLA at risk</TableHead>
            <TableHead className="text-right">Waiting on you</TableHead>
            <TableHead className="pr-4 text-right">Priorities to review</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {board.people.map((p) => {
            const key = p.name ?? "";
            const theirs = board.tickets.filter((t) => (t.assignee ?? "") === key);
            const risk = theirs.filter(atRisk).length;
            return (
              <WorkloadRows key={key} open={open === key} tickets={theirs} onChange={onChange}>
                <TableCell className="pl-2">
                  <Button variant="ghost" size="sm" aria-expanded={open === key} onClick={() => setOpen(open === key ? null : key)} className={cn(!p.name && "text-muted-foreground")}>
                    <ChevronRight className={cn("transition-transform duration-150", open === key && "rotate-90")} aria-hidden="true" />
                    {p.name ?? NO_ENGINEER}
                  </Button>
                  {p.name && working[p.name] && working[p.name].state !== "on_shift" && (
                    <span className={cn("ml-1 text-xs", working[p.name].state === "on_leave" && p.open > 0 ? "font-semibold text-critical" : "text-muted-foreground")}>
                      {stateWords(working[p.name])}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">{p.open}</TableCell>
                <TableCell className="text-right tabular-nums">{p.p1_p2}</TableCell>
                <TableCell className={cn("text-right tabular-nums", risk > 0 && "font-semibold text-critical")}>{risk}</TableCell>
                <TableCell className="text-right tabular-nums">{theirs.filter(withLead).length}</TableCell>
                <TableCell className="pr-4 text-right tabular-nums">{p.waiting_review}</TableCell>
              </WorkloadRows>
            );
          })}
        </TableBody>
      </Table>
    </Card>
  );
}

function WorkloadRows({ open, tickets, onChange, children }: { open: boolean; tickets: BoardTicket[]; onChange: () => unknown; children: React.ReactNode }) {
  return (
    <>
      <TableRow>{children}</TableRow>
      {open && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={6} className="bg-muted/40 p-0 whitespace-normal">
            <ul role="list">
              {tickets.map((t) => (
                <TicketRow
                  key={t.id}
                  ticket={t}
                  facts={[appOf(t), !atRisk(t) && slaWords(t)]}
                  actions={
                    <>
                      <StagePill ticket={t} />
                      <AssignControl ticketId={t.id} assignee={t.assignee} onDone={onChange} />
                    </>
                  }
                />
              ))}
            </ul>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

/**
 * The lead's home: what waits for the lead (tickets escalated after three failed fixes, closure notes to approve,
 * tickets with no engineer, tickets near or past their SLA), then who has what. The whole queue is the Overview.
 */
export function LeadDesk() {
  const { board, error, load } = useBoard();
  const [attention, setAttention] = useState<Attention | null>(null);
  useEffect(() => {
    incidentService.getAttention().then(setAttention, () => setAttention(null));
  }, [board]);
  // An engineer for each ticket nobody has: who knows the application and has room.
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [limit, setLimit] = useState<number | null>(null); // open tickets at which an engineer gets no more suggestions
  useEffect(() => {
    pipelineService.suggestions().then(
      (s) => {
        setSuggestions(s.suggestions);
        setLimit(s.limit);
      },
      () => setSuggestions([])
    );
  }, [board]);
  const suggested = new Map(suggestions.map((s) => [s.id, s]));
  // The clock is read in the browser only: prerendered, the date and ages would be the build's.
  const now = useSyncExternalStore(never, thisMinute, () => null);

  const tickets = board?.tickets ?? [];
  const lists = board && {
    escalated: tickets.filter((t) => t.stage === "needs_lead"),
    notes: tickets.filter((t) => t.stage === "in_review"),
    unassigned: tickets.filter((t) => !t.assignee),
    risk: tickets.filter(atRisk),
  };
  const decisions = lists ? lists.escalated.length + lists.notes.length + lists.unassigned.length : 0;
  const engineers = board?.people.filter((p) => p.name).length ?? 0;
  const open = (t: BoardTicket, label: string) => (
    <Button size="sm" variant="secondary" nativeButton={false} render={<Link href={ticketHref(t)} />}>
      {label}
    </Button>
  );

  return (
    <AppShell>
      <PageHeader
        title="Lead desk"
        context={
          !board || now === null ? (
            error ? undefined : (
              <>
                <span className="sr-only">Loading…</span>
                <Skeleton className="mt-1 h-3.5 w-72 max-w-full" />
              </>
            )
          ) : (
            `${new Date(now).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })} · ` +
            `${decisions ? count(decisions, "ticket waits", "tickets wait") : "Nothing waits"} for you · ` +
            `${count(board.totals.open, "open ticket", "open tickets")} with ${count(engineers, "engineer", "engineers")}`
          )
        }
        actions={
          <Button variant="secondary" onClick={load}>
            Refresh
          </Button>
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <MajorIncidents attention={attention} tickets={tickets} now={now} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile variant={lists?.escalated.length ? "primary" : "secondary"} label="Escalated to you" value={lists ? lists.escalated.length : "—"} window="three fixes did not work" href="#escalated" />
        <StatTile label="Closure notes to approve" value={lists ? lists.notes.length : "—"} window="submitted by engineers" href="#notes" />
        <StatTile label="Unassigned" value={lists ? lists.unassigned.length : "—"} window="no engineer yet" href="#unassigned" />
        <StatTile label="SLA at risk" value={lists ? lists.risk.length : "—"} window="near breach or past it" href="#risk" />
      </div>

      {lists && limit !== null && lists.unassigned.length > suggestions.length && (
        <Alert>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-semibold">{count(lists.unassigned.length - suggestions.length, "ticket has", "tickets have")} no one with room.</span>{" "}
              {`Nobody holding ${limit} open tickets is suggested another, unless it is a P1 or P2. Assign by hand, add people to the team, or raise the limit.`}
            </span>
            <Button size="sm" variant="secondary" nativeButton={false} render={<Link href="/lead/team" />}>
              Hours and leave
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Section id="escalated" title="Escalated to you" empty="No ticket is escalated. A ticket comes here after three suggested fixes did not work." tickets={lists ? lists.escalated : null}>
          {(t) => <TicketRow key={t.id} ticket={t} facts={[appOf(t), t.assignee ?? NO_ENGINEER, "three fixes did not work"]} actions={open(t, "Open ticket")} />}
        </Section>
        <Section id="notes" title="Closure notes to approve" empty="No closure note waits for your approval." tickets={lists ? lists.notes : null}>
          {(t) => (
            <TicketRow
              key={t.id}
              ticket={t}
              facts={[appOf(t), t.lead_by && `submitted by ${t.lead_by}`, t.closure_score != null && `Closure Quality score: ${t.closure_score} of 6`]}
              actions={open(t, "Review closure note")}
            />
          )}
        </Section>
        <Section
          id="unassigned"
          title="Unassigned"
          empty="Every open ticket has an engineer."
          tickets={lists ? lists.unassigned : null}
          action={suggestions.length > 0 && <AssignSuggested suggestions={suggestions} onDone={load} />}
        >
          {(t) => (
            <TicketRow
              key={t.id}
              ticket={t}
              facts={[appOf(t), now !== null && ageOf(t, now) && `open ${ageOf(t, now)!.words}`, !atRisk(t) && slaWords(t)]}
              note={suggested.has(t.id) ? `Suggested: ${suggested.get(t.id)!.name} · ${suggested.get(t.id)!.reason}` : limit !== null && "No one has room"}
              actions={<AssignControl ticketId={t.id} assignee={t.assignee} suggested={suggested.get(t.id)?.name} onDone={load} />}
            />
          )}
        </Section>
        <Section id="risk" title="SLA at risk" empty="No ticket is near its SLA or past it." tickets={lists ? lists.risk : null}>
          {(t) => (
            <TicketRow
              key={t.id}
              ticket={t}
              facts={[appOf(t)]}
              actions={
                <>
                  <AssignControl ticketId={t.id} assignee={t.assignee} onDone={load} />
                  {open(t, "Open")}
                </>
              }
            />
          )}
        </Section>
      </div>

      {board && board.people.length > 0 && <Workload board={board} onChange={load} />}
      {board && <ActivityCard title="Recent activity · today" asOf={board} />}
    </AppShell>
  );
}
