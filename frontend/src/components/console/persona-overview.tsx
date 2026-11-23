"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { Play, Search } from "lucide-react";
import { AppShell } from "@/components/console/app-shell";
import { CountUp } from "@/components/console/count-up";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import {
  AGES, ActivityCard, AgentsToday, BoardTicket, NO_ENGINEER, STATUSES, StagePill, ageOf, and, appOf, count, ticketHref,
  useBoard, useToday,
} from "@/components/console/persona-parts";
import { SectionHead, Status, dueWords, span } from "@/components/console/sync-parts";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { pipelineService } from "@/services/pipeline-service";
import { cn } from "cn";

const SELECT =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";
// The cards in priority groups, as on the design canvas.
const SECTIONS: { title: string; has: (t: BoardTicket) => boolean }[] = [
  { title: "P1 and P2", has: (t) => t.priority !== null && t.priority <= 2 },
  { title: "P3 to P5", has: (t) => (t.priority ?? 0) >= 3 },
  { title: "Not triaged yet", has: (t) => t.priority === null },
];
const TILE = "h-auto min-w-32 flex-1 basis-32 flex-col items-start gap-0 whitespace-normal rounded-[14px] px-4 py-2.5 text-left";

const never = () => () => {};
const thisMinute = () => Math.floor(Date.now() / 60000) * 60000;

/** One ticket as a card: id and priority, the summary, application, its work status, age and engineer. */
function TicketCard({ ticket, now }: { ticket: BoardTicket; now: number | null }) {
  const age = now === null ? null : ageOf(ticket, now);
  return (
    <Link href={ticketHref(ticket)} className="group block rounded-[20px] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none">
      <Card className={cn("h-full gap-2 px-4 py-3 transition-colors duration-150 group-hover:border-border-strong group-hover:bg-muted/40", ticket.priority === 1 && "border-2 border-primary")}>
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-xs text-muted-foreground">{ticket.id}</span>
          <PriorityChip priority={ticket.priority} />
        </div>
        <p className="line-clamp-2 text-sm font-semibold">{ticket.summary || "No summary"}</p>
        <p className="text-xs text-muted-foreground">{appOf(ticket)}</p>
        <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1">
          <StagePill ticket={ticket} />
          {ticket.fix_verdict === "no_match" && (
            <Badge variant="destructive" title="Resolution found no runbook article for this ticket">
              No KB
            </Badge>
          )}
          <span className="text-xs text-muted-foreground">
            {[age?.words, ticket.assignee ?? "Unassigned"].filter(Boolean).join(" · ")}
          </span>
        </div>
      </Card>
    </Link>
  );
}

/**
 * The Overview (19 Nov review, design canvas): every open ticket for every role, by work status. The lead also
 * runs the agents and sees who has what. My worklist (my-worklist.tsx) is the viewer's own work.
 */
export function PersonaOverview({ lead }: { lead: boolean }) {
  const { board, error, setError, load } = useBoard();
  const today = useToday(board);
  const [status, setStatus] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [app, setApp] = useState("");
  const [age, setAge] = useState<string | null>(null);
  const [noKb, setNoKb] = useState(false); // only tickets Resolution found no runbook fix for
  const [running, setRunning] = useState(false);
  const [ran, setRan] = useState<string | null>(null);
  // The clock is read in the browser only: prerendered, the date and ages would be the build's.
  const now = useSyncExternalStore(never, thisMinute, () => null);

  // The agents also run by themselves after each Jira sync; this is for a lead who does not want to wait.
  const runAgents = async () => {
    setRunning(true);
    setRan(null);
    try {
      const dq = await pipelineService.run("data-quality");
      const triage = await pipelineService.run("triage");
      const failed = dq.model_errors + triage.model_errors;
      setRan(
        (dq.evaluated + triage.evaluated === 0
          ? "Nothing was waiting for the agents."
          : `Data Quality checked ${dq.evaluated}, Triage set a priority on ${triage.evaluated}.`) + (failed ? ` The model failed on ${failed}.` : "")
      );
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't run the agents");
    } finally {
      setRunning(false);
    }
  };

  const t = board?.totals;
  const tickets = board?.tickets ?? [];
  const needDetails = tickets.filter((x) => x.stage === "awaiting_info");
  const drafted = needDetails.filter((x) => x.has_draft).length;
  const noRunbook = tickets.filter((x) => x.fix_verdict === "no_match" && x.fix_answer !== "partly" && x.fix_answer !== "worked");
  const wrong = [
    t?.sla_breached && `${count(t.sla_breached, "ticket has", "tickets have")} breached SLA`,
    t?.sla_at_risk && `${count(t.sla_at_risk, "ticket is", "tickets are")} close to breach`,
    lead && t?.unassigned && `${count(t.unassigned, "ticket has", "tickets have")} no engineer`,
  ].filter((part): part is string => !!part);
  const nearest = tickets.reduce<BoardTicket | null>(
    (first, x) => (x.minutes_left !== null && (!first || x.minutes_left < first.minutes_left!) ? x : first),
    null
  );

  const chosen = STATUSES.find((s) => s.key === status);
  const byStatus = (chosen ? tickets.filter((x) => chosen.stages.includes(x.stage)) : tickets).filter((x) => !noKb || noRunbook.includes(x));
  const apps = [...byStatus.reduce((c, x) => c.set(appOf(x), (c.get(appOf(x)) ?? 0) + 1), new Map<string, number>())].sort((a, b) => b[1] - a[1]);
  const ageFilter = AGES.find((a) => a.key === age);
  const q = query.trim().toLowerCase();
  const last = Number.MAX_SAFE_INTEGER;
  const listed = byStatus
    .filter(
      (x) =>
        (!app || appOf(x) === app) &&
        (!ageFilter || (now !== null && ageFilter.has(ageOf(x, now)?.minutes ?? 0))) &&
        (!q || [x.id, x.summary, x.application, x.assignee].some((v) => v?.toLowerCase().includes(q)))
    )
    .sort((a, b) => (a.priority ?? last) - (b.priority ?? last) || (a.minutes_left ?? last) - (b.minutes_left ?? last));
  const pick = (key: string | null) => {
    setStatus(key);
    setApp("");
    setNoKb(false);
  };

  return (
    <AppShell>
      <PageHeader
        title="Overview"
        context={
          !t || now === null ? (
            error ? undefined : (
              <>
                <span className="sr-only">Loading…</span>
                <Skeleton className="mt-1 h-3.5 w-72 max-w-full" />
              </>
            )
          ) : (
            `${new Date(now).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })} · ` +
            `${count(t.open, "open ticket", "open tickets")} from Jira and the mailbox${t.unassigned ? ` · ${t.unassigned} with no engineer` : ""}`
          )
        }
        actions={
          <>
            {lead && now !== null && (
              <Button onClick={runAgents} disabled={running}>
                <Play />
                {running ? "Running…" : "Run agents"}
              </Button>
            )}
            <Button variant="secondary" onClick={load}>
              Refresh
            </Button>
          </>
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {ran && (
        <Alert aria-live="polite">
          <AlertDescription>{ran}</AlertDescription>
        </Alert>
      )}

      {t && (
        <p role="status" className="text-[13px]">
          <Status ok={wrong.length === 0}>
            <span>
              <span className="font-semibold">{wrong.length ? `${and.format(wrong)}.` : "All clear on SLA."}</span>
              {nearest &&
                (nearest.minutes_left! < 0
                  ? ` The most overdue is ${span(nearest.minutes_left!)} over.`
                  : ` The nearest deadline is ${nearest.due_at ? dueWords(nearest.due_at) : `in ${span(nearest.minutes_left!)}`}.`)}
            </span>
          </Status>
        </p>
      )}

      <AgentsToday today={today} />

      {/* Work statuses: pressing one lists only those tickets. */}
      <section aria-label="Open tickets by status" className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" aria-pressed={!chosen} onClick={() => pick(null)} className={cn(TILE, !chosen && "border-2 border-foreground")}>
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] uppercase">All open</span>
            <span className="text-2xl leading-8 tabular-nums">{board ? <CountUp value={tickets.length} /> : "—"}</span>
            <span className="text-xs font-normal text-muted-foreground">{t ? `${t.sla_breached} past SLA` : " "}</span>
          </Button>
          {STATUSES.map((s) => {
            const n = tickets.filter((x) => s.stages.includes(x.stage)).length;
            return (
              <Button key={s.key} variant="secondary" aria-pressed={status === s.key} onClick={() => pick(status === s.key ? null : s.key)} className={cn(TILE, status === s.key && "border-2 border-foreground")}>
                <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] uppercase">{s.label}</span>
                <span className="text-2xl leading-8 tabular-nums">{board ? <CountUp value={n} /> : "—"}</span>
                <span className="text-xs font-normal text-muted-foreground">{s.sub}</span>
              </Button>
            );
          })}
          <div className={cn(TILE, "flex rounded-[14px] border border-dashed border-border-strong")}>
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] uppercase">Closed today</span>
            <span className="text-2xl leading-8 font-medium tabular-nums">{today ? today.closed : "—"}</span>
            <span className="text-xs text-muted-foreground">closure notes sent</span>
          </div>
        </div>
      </section>

      {needDetails.length > 0 && status !== "needs" && (
        <Alert>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-semibold">{count(needDetails.length, "ticket needs", "tickets need")} details.</span>{" "}
              {drafted ? `Data Quality drafted the question for ${drafted}; the engineer sends it.` : "The reporter has to say more."}
            </span>
            <Button size="sm" variant="secondary" onClick={() => pick("needs")}>
              Show them
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {(noRunbook.length > 0 || noKb) && (
        <Alert className={noKb ? "border-primary" : undefined}>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-semibold">
                {noRunbook.length ? `${count(noRunbook.length, "ticket has", "tickets have")} no runbook fix.` : "No ticket is without a runbook fix now."}
              </span>{" "}
              The knowledge base doesn&rsquo;t cover {noRunbook.length === 1 ? "it" : "them"}: work it out with AI on the ticket page; the fix becomes a knowledge article after it is closed.
            </span>
            <Button size="sm" variant={noKb ? "default" : "secondary"} aria-pressed={noKb} onClick={() => setNoKb(!noKb)}>
              {noKb ? "Show all" : "Show them"}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap items-center gap-2 px-4 py-3">
          <div className="relative flex-[2_1_16rem]">
            <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
            <Input aria-label="Search the tickets" placeholder="Search by ticket ID, summary, application or engineer" value={query} onChange={(e) => setQuery(e.target.value)} className="pl-8" />
          </div>
          <div className="flex-[1_1_11rem]">
            <select aria-label="Application" value={app} onChange={(e) => setApp(e.target.value)} className={SELECT}>
              <option value="">All applications ({byStatus.length})</option>
              {apps.map(([name, c]) => (
                <option key={name} value={name}>
                  {name} ({c})
                </option>
              ))}
            </select>
          </div>
          <div role="group" aria-label="Age" className="flex flex-wrap items-center gap-1">
            <span className="pr-1 text-xs text-muted-foreground">Age</span>
            {[{ key: null, label: "Any" }, ...AGES].map((a) => (
              <Button key={a.key ?? "any"} size="sm" variant={age === a.key ? "default" : "secondary"} aria-pressed={age === a.key} onClick={() => setAge(a.key)}>
                {a.label}
              </Button>
            ))}
          </div>
        </div>
      </Card>

      {!board ? (
        error ? null : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-32 rounded-[20px]" />
            ))}
          </div>
        )
      ) : listed.length === 0 ? (
        <Card>
          <p className="px-4 text-muted-foreground">{tickets.length ? "No tickets match the filters." : "No open tickets."}</p>
        </Card>
      ) : (
        SECTIONS.map((section) => {
          const cards = listed.filter(section.has);
          return (
            cards.length > 0 && (
              <section key={section.title} aria-label={section.title} className="flex flex-col gap-2">
                <h2 className="pl-1 text-sm font-semibold">
                  {section.title} <span className="font-normal text-muted-foreground tabular-nums">{cards.length}</span>
                </h2>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {cards.map((x) => (
                    <TicketCard key={x.id} ticket={x} now={now} />
                  ))}
                </div>
              </section>
            )
          );
        })
      )}

      <div className="grid items-start gap-4 lg:grid-cols-2 lg:[&>*:first-child:nth-last-child(odd)]:col-span-full">
        {lead && board && board.people.length > 0 && (
          <Card className="gap-0 py-0">
            <SectionHead title="Workload by engineer" />
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Engineer</TableHead>
                  <TableHead className="text-right">Open</TableHead>
                  <TableHead className="text-right">P1 and P2</TableHead>
                  <TableHead className="text-right">SLA breached</TableHead>
                  <TableHead className="pr-4 text-right">Priority to review</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {board.people.map((p) => (
                  <TableRow key={p.name ?? ""}>
                    <TableCell className={p.name ? "pl-4 font-medium" : "pl-4 text-muted-foreground"}>{p.name ?? NO_ENGINEER}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.open}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.p1_p2}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.breached}</TableCell>
                    <TableCell className="pr-4 text-right tabular-nums">{p.waiting_review}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
        {board && <ActivityCard title="Recent activity · today" asOf={board} />}
      </div>
    </AppShell>
  );
}
