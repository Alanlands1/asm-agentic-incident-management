"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { BookX, Clock, Play, Search, TriangleAlert } from "lucide-react";
import { AppShell } from "@/components/console/app-shell";
import { CountUp } from "@/components/console/count-up";
import { SyncsCard } from "@/components/console/dashboard";
import { ResetDemoButton } from "@/components/console/reset-demo-button";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import {
  AGES, ActivityCard, AgentsToday, BoardTicket, STATUSES, StagePill, ageOf, and, appOf, count, ticketHref,
  useBoard, useToday,
} from "@/components/console/persona-parts";
import { Status, dueWords, span } from "@/components/console/sync-parts";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { usePerson } from "@/lib/view-as";
import { incidentService } from "@/services/incident-service";
import { pipelineService } from "@/services/pipeline-service";
import { Attention } from "@/types/incident";
import { cn } from "cn";

const SELECT =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";
// The cards in priority groups, as on the design canvas.
const SECTIONS: { title: string; has: (t: BoardTicket) => boolean }[] = [
  { title: "P1 and P2", has: (t) => t.priority !== null && t.priority <= 2 },
  { title: "P3 to P5", has: (t) => (t.priority ?? 0) >= 3 },
  { title: "Not triaged yet", has: (t) => t.priority === null },
];
const TILE = "h-auto min-w-0 flex-col items-start justify-start gap-0 whitespace-normal rounded-[14px] px-3 py-2.5 text-left";

// Close to breaching the SLA, or past it: the tickets to act on first.
export const atRisk = (t: BoardTicket) => t.sla_state === "breach_likely" || t.sla_state === "breached";

const never = () => () => {};
const thisMinute = () => Math.floor(Date.now() / 60000) * 60000;

/** One ticket as a card: id and priority, the summary, application, its work status, age and engineer. */
function TicketCard({ ticket, now }: { ticket: BoardTicket; now: number | null }) {
  const age = now === null ? null : ageOf(ticket, now);
  return (
    <Link href={ticketHref(ticket)} className="group block rounded-[20px] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none">
      <Card className={cn("h-full gap-2 px-4 py-3 transition-colors duration-150 group-hover:border-border-strong group-hover:bg-muted/40", ticket.priority === 1 && "border-2 border-primary bg-selected/50")}>
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-xs text-muted-foreground">{ticket.id}</span>
          <PriorityChip priority={ticket.priority} />
        </div>
        <p className="line-clamp-2 text-sm font-semibold">{ticket.summary || "No summary"}</p>
        <p className="flex flex-wrap items-center justify-between gap-x-2 text-xs text-muted-foreground">
          {appOf(ticket)}
          {ticket.sla_state && ticket.minutes_left !== null && (
            <span className={cn("inline-flex items-center gap-1 whitespace-nowrap tabular-nums", atRisk(ticket) ? "font-semibold text-critical" : ticket.sla_state === "watch" && "font-medium text-foreground")}>
              {atRisk(ticket) ? <TriangleAlert className="size-3.5" aria-hidden="true" /> : <Clock className="size-3.5" aria-hidden="true" />}
              {`SLA ${span(Math.abs(ticket.minutes_left))} ${ticket.minutes_left < 0 ? "over" : "left"}`}
            </span>
          )}
        </p>
        <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-1">
          <StagePill ticket={ticket} />
          {ticket.fix_verdict === "no_match" && (
            <Badge variant="destructive" className="border-dashed text-[11px] font-semibold" title="Resolution found no knowledge article for this ticket. Use the AI assistant on the ticket page to work out a fix.">
              <BookX aria-hidden="true" />
              No knowledge article
            </Badge>
          )}
          <span className="ml-auto text-xs text-muted-foreground">
            {[age?.words, ticket.assignee ?? "Unassigned"].filter(Boolean).join(" · ")}
          </span>
        </div>
      </Card>
    </Link>
  );
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

/**
 * A major incident on top of the Overview (19 Nov canvas): declared storms in red with who declared it and the last
 * update to stakeholders; a storm nobody declared yet in amber, with a way to the Incidents page to decide.
 */
export function MajorIncidents({ attention, tickets, now }: { attention: Attention | null; tickets: BoardTicket[]; now: number | null }) {
  if (!attention) return null;
  const summary = (id: string) => tickets.find((t) => t.id === id)?.summary ?? attention.p1_p2.find((i) => i.ticket_id === id)?.summary ?? id;
  const declared = attention.storms.filter((s) => s.status === "declared");
  const suspected = attention.storms.filter((s) => s.status === "open");
  return (
    <>
      {declared.map((s) => {
        const main = attention.p1_p2.find((i) => i.ticket_id === s.main_ticket_id);
        const age = now === null ? null : ageOf({ opened_at: s.opened_at } as BoardTicket, now)?.words;
        return (
          <Card key={s.id} className="flex-row flex-wrap items-center gap-4 border-0 bg-primary px-5 py-[18px] text-primary-foreground">
            <div className="flex min-w-0 flex-[999_1_380px] flex-col gap-1.5">
              <p className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-primary-foreground px-2.5 py-[3px] text-xs font-semibold whitespace-nowrap text-primary">P1 · Major incident</span>
                <span className="font-mono text-[13px] opacity-85">
                  {[s.main_ticket_id, s.application, age ? `${age} open` : `open since ${clock(s.opened_at)}`].filter(Boolean).join(" · ")}
                </span>
              </p>
              <h2 className="text-[19px] leading-snug font-bold">
                {summary(s.main_ticket_id)}
                {s.ticket_count > 1 && ` and ${count(s.ticket_count - 1, "other", "others")}`}
              </h2>
              <p className="text-[13px] opacity-90">
                {[
                  s.declared_by && `Declared by ${s.declared_by}${s.declared_at ? ` at ${clock(s.declared_at)}` : ""}`,
                  `${count(s.people, "person", "people")} reporting`,
                  main?.last_sent
                    ? `last update to stakeholders ${clock(main.last_sent.sent_at)} by ${main.last_sent.sent_by}`
                    : main && `first stakeholder message ${main.first_message.minutes_left >= 0 ? `due in ${main.first_message.minutes_left} min` : "overdue"}`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <Button variant="secondary" size="lg" className="border-primary-foreground text-primary" nativeButton={false} render={<Link href="/incidents" />}>
                Open incident
              </Button>
              <Button
                variant="ghost"
                size="lg"
                className="border border-primary-foreground text-primary-foreground hover:bg-primary-foreground/15 hover:text-primary-foreground"
                nativeButton={false}
                render={<Link href={ticketHref({ id: s.main_ticket_id })} />}
              >
                Open ticket
              </Button>
            </div>
          </Card>
        );
      })}
      {suspected.map((s) => (
        <Alert key={s.id} className="border-p2 bg-p2/15">
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-semibold">Possible major incident: </span>
              {`${count(s.ticket_count, "ticket", "tickets")} about ${s.application ?? "the same problem"} since ${clock(s.opened_at)}, like ${s.main_ticket_id} “${summary(s.main_ticket_id)}”. Not yet declared.`}
            </span>
            <Button size="sm" variant="secondary" nativeButton={false} render={<Link href="/incidents" />}>
              Decide on Incidents
            </Button>
          </AlertDescription>
        </Alert>
      ))}
    </>
  );
}

/**
 * The Overview (19 Nov review, design canvas): every open ticket for every role, by work status. The lead also
 * runs the agents; who has what is on the Lead desk (lead-desk.tsx). My worklist (my-worklist.tsx) is the viewer's own work.
 */
export function PersonaOverview({ lead, admin = false }: { lead: boolean; admin?: boolean }) {
  // An engineer sees only the tickets assigned to them, and the figures for those; a lead and the admin see all.
  const viewer = usePerson();
  const mine = lead ? undefined : viewer;
  const { board, error, setError, load } = useBoard(mine);
  const today = useToday(board, mine);
  const [attention, setAttention] = useState<Attention | null>(null);
  useEffect(() => {
    incidentService.getAttention().then(setAttention, () => setAttention(null));
  }, [board]);
  const [status, setStatus] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [app, setApp] = useState("");
  const [age, setAge] = useState<string | null>(null);
  const [noKb, setNoKb] = useState(false); // only tickets Resolution found no runbook fix for
  const [risk, setRisk] = useState(false); // only tickets close to breaching the SLA or past it
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
      setError(e instanceof Error ? e.message : "Couldn't run the agents. Try again.");
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
    t?.sla_at_risk && `${count(t.sla_at_risk, "ticket is", "tickets are")} near breach`,
    lead && t?.unassigned && `${count(t.unassigned, "ticket is", "tickets are")} unassigned`,
  ].filter((part): part is string => !!part);
  const nearest = tickets.reduce<BoardTicket | null>(
    (first, x) => (x.minutes_left !== null && (!first || x.minutes_left < first.minutes_left!) ? x : first),
    null
  );

  const chosen = STATUSES.find((s) => s.key === status);
  const byStatus = (chosen ? tickets.filter((x) => chosen.stages.includes(x.stage)) : tickets).filter((x) => (!noKb || noRunbook.includes(x)) && (!risk || atRisk(x)));
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
    setRisk(false);
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
            (mine
              ? `${count(t.open, "open ticket", "open tickets")} assigned to you`
              : `${count(t.open, "open ticket", "open tickets")} from Jira and the mailbox${t.unassigned ? ` · ${t.unassigned} unassigned` : ""}`)
          )
        }
        actions={
          <>
            {admin && <ResetDemoButton />}
            {admin && (
              <Button variant="secondary" nativeButton={false} render={<Link href="/incidents" />}>
                Incidents
              </Button>
            )}
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

      <MajorIncidents attention={attention} tickets={tickets} now={now} />

      {t && (
        <p role="status" className="text-[13px]">
          <Status ok={wrong.length === 0}>
            <span>
              <span className="font-semibold">{wrong.length ? `${and.format(wrong)}.` : "No SLA risks."}</span>
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
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
          <Button variant="secondary" aria-pressed={!chosen && !risk} onClick={() => pick(null)} className={cn(TILE, !chosen && !risk && "border-2 border-foreground")}>
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] uppercase">All open</span>
            <span className="text-2xl leading-8 tabular-nums">{board ? <CountUp value={tickets.length} /> : "—"}</span>
            <span className="text-xs font-normal text-muted-foreground">{t ? `${t.sla_breached} past SLA` : " "}</span>
          </Button>
          <Button
            variant="secondary"
            aria-pressed={risk}
            onClick={() => {
              pick(null);
              setRisk(!risk);
            }}
            className={cn(TILE, risk && "border-2 border-foreground")}
          >
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] uppercase">SLA at risk</span>
            <span className={cn("text-2xl leading-8 tabular-nums", tickets.some(atRisk) && "text-critical")}>{board ? <CountUp value={tickets.filter(atRisk).length} /> : "—"}</span>
            <span className="text-xs font-normal text-muted-foreground">near breach or past it</span>
          </Button>
          {STATUSES.map((s) => {
            const n = tickets.filter((x) => s.stages.includes(x.stage)).length;
            return (
              <Button key={s.key} variant="secondary" aria-pressed={status === s.key && !risk} onClick={() => pick(status === s.key && !risk ? null : s.key)} className={cn(TILE, status === s.key && !risk && "border-2 border-foreground")}>
                <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] uppercase">{s.label}</span>
                <span className="text-2xl leading-8 tabular-nums">{board ? <CountUp value={n} /> : "—"}</span>
                <span className="text-xs font-normal text-muted-foreground">{s.sub}</span>
              </Button>
            );
          })}
          <div className={cn(TILE, "flex rounded-[14px] border border-dashed border-border-strong")}>
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] uppercase">Today</span>
            <span className="flex items-baseline gap-1 text-2xl leading-8 font-medium tabular-nums">
              {today?.opened ?? (today ? today.closed : "—")}
              <span className="text-xs font-normal text-muted-foreground">{today?.opened === undefined ? "closed" : "new"}</span>
            </span>
            <span className="text-xs text-muted-foreground">
              {today?.opened === undefined
                ? "closure notes sent"
                : `${today.closed} closed, backlog ${today.opened === today.closed ? "unchanged" : `${today.opened > today.closed ? "up" : "down"} ${Math.abs(today.opened - today.closed)}`}`}
            </span>
          </div>
        </div>
      </section>

      <Card className="gap-0 py-0">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-3 px-4 py-3">
          <label className="flex flex-[2_1_16rem] flex-col gap-1.5">
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">Search</span>
            <span className="relative">
              <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
              <Input placeholder="Search by ticket ID, summary, application or engineer" value={query} onChange={(e) => setQuery(e.target.value)} className="pl-8" />
            </span>
          </label>
          <label className="flex flex-[1_1_11rem] flex-col gap-1.5">
            <span className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">Application</span>
            <select value={app} onChange={(e) => setApp(e.target.value)} className={SELECT}>
              <option value="">All applications ({byStatus.length})</option>
              {apps.map(([name, c]) => (
                <option key={name} value={name}>
                  {name} ({c})
                </option>
              ))}
            </select>
          </label>
          <div role="group" aria-labelledby="age-label" className="flex flex-col gap-1.5">
            <span id="age-label" className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">Age</span>
            <div className="flex flex-wrap items-center gap-1">
              {[{ key: null, label: "Any" }, ...AGES].map((a) => (
                <Button key={a.key ?? "any"} size="sm" variant={age === a.key ? "default" : "secondary"} aria-pressed={age === a.key} onClick={() => setAge(a.key)}>
                  {a.label}
                </Button>
              ))}
            </div>
          </div>
        </div>
      </Card>

      {needDetails.length > 0 && status !== "needs" && (
        <Alert>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-semibold">{count(needDetails.length, "ticket needs", "tickets need")} details.</span>{" "}
              {drafted ? `Data Quality drafted the request for ${drafted}; the engineer sends it.` : "Awaiting information from the requester."}
            </span>
            <Button size="sm" variant="secondary" onClick={() => pick("needs")}>
              Show
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {(noRunbook.length > 0 || noKb) && (
        <Alert className={noKb ? "border-primary" : undefined}>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-semibold">
                {noRunbook.length ? `${count(noRunbook.length, "ticket has", "tickets have")} no runbook fix.` : "Every open ticket has a runbook fix."}
              </span>{" "}
              The knowledge base doesn&rsquo;t cover {noRunbook.length === 1 ? "it" : "them"}: work it out with AI on the ticket page; the fix becomes a knowledge article after it is closed.
            </span>
            <Button size="sm" variant={noKb ? "default" : "secondary"} aria-pressed={noKb} onClick={() => setNoKb(!noKb)}>
              {noKb ? "Show all" : "Show"}
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {!board ? (
        error ? null : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" aria-busy="true">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-32 rounded-[20px]" />
            ))}
          </div>
        )
      ) : listed.length === 0 ? (
        <Card>
          <p className="px-4 text-muted-foreground">{tickets.length ? "No tickets match the filters." : mine ? "No open tickets are assigned to you." : "No open tickets."}</p>
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
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {cards.map((x) => (
                    <TicketCard key={x.id} ticket={x} now={now} />
                  ))}
                </div>
              </section>
            )
          );
        })
      )}

      {board && <ActivityCard title="Recent activity · today" asOf={board} />}
      {admin && <SyncsCard />}
    </AppShell>
  );
}
