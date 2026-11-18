"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, Play, Search } from "lucide-react";
import { AppShell } from "@/components/console/app-shell";
import { STAGES } from "@/components/console/dashboard";
import { ListRow } from "@/components/console/list-row";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import { CountUp } from "@/components/console/count-up";
import { StatTile } from "@/components/console/stat-tile";
import { SectionHead, SlaClock, SlaGauge, Status, dueWords, span } from "@/components/console/sync-parts";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiClient } from "@/lib/api-client";
import { usePerson } from "@/lib/view-as";
import { dashboardService } from "@/services/dashboard-service";
import { pipelineService } from "@/services/pipeline-service";
import { DashboardSummary } from "@/types/dashboard";
import { PipelineTicket } from "@/types/pipeline";
import { cn } from "cn";

type Board = {
  totals: { open: number; p1_p2: number; sla_breached: number; sla_at_risk: number; waiting_review: number; unassigned: number };
  people: { name: string | null; open: number; p1_p2: number; breached: number; waiting_review: number }[];
  tickets: {
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
    // The ones below are missing from a backend that has not been restarted since they were added.
    triage_reason?: string | null;
    reported_priority?: number | null;
    missing?: string[];
    has_draft?: boolean;
    due_at?: string | null;
    runbook?: string | null;
  }[];
};
type Ticket = Board["tickets"][number];

const STAGE_WORDS: Record<string, string> = Object.fromEntries(STAGES);
const NO_ENGINEER = "No engineer yet";
const PAGE_SIZE = 10;
const SELECT =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";
const PRIORITY_LABELS: Record<number, string> = { 1: "Highest", 2: "High", 3: "Medium", 4: "Low" };
const MISSING_WORDS: Record<string, string> = {
  what_happened: "what happened",
  application: "which application",
  when: "when it happened",
  who_affected: "who is affected",
  error_message: "the error message",
  steps_to_reproduce: "the steps to reproduce",
};
// The queue by priority, as the tiles over the table: P1 red, P2 amber, the rest green.
const GROUPS: { key: string; label: string; has: (t: Ticket) => boolean; look: string }[] = [
  { key: "p1", label: "P1", has: (t) => t.priority === 1, look: "border-primary bg-primary text-primary-foreground hover:bg-primary-hover" },
  { key: "p2", label: "P2", has: (t) => t.priority === 2, look: "border-p2 bg-p2 text-p2-foreground hover:bg-p2/85" },
  { key: "p3", label: "P3 to P4", has: (t) => (t.priority ?? 0) >= 3, look: "border-p3 bg-p3 text-white hover:bg-p3/85" },
  { key: "none", label: "Not triaged yet", has: (t) => t.priority === null, look: "" },
];
const and = new Intl.ListFormat("en-GB", { type: "conjunction" });
const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const appOf = (t: Ticket) => t.application ?? "No application";
const ticketHref = (t: Ticket) => `/tickets/${encodeURIComponent(t.id)}`;

/** How the priority in force compares with the reported one; nothing when either is unknown. */
function versusReported(t: Ticket) {
  if (!t.priority || !t.reported_priority) return null;
  if (t.priority === t.reported_priority) return "Same as reported";
  const label = PRIORITY_LABELS[t.reported_priority] ?? `P${t.reported_priority}`;
  return `${t.priority < t.reported_priority ? "Raised" : "Lowered"} from ${label}`;
}

/** What a ticket waits for. `toAssign`: the lead looks at a ticket with no engineer, and assigning it comes first. */
function nextStep(t: Ticket, toAssign: boolean) {
  if (toAssign) return "Assign an engineer in Jira";
  if (t.stage === "triaged") return `Review the recommended P${t.priority}`;
  if (t.priority_from === "reviewed") return "Priority decided. Work it in Jira";
  return STAGE_WORDS[t.stage] ?? t.stage;
}

function Sla({ ticket }: { ticket: Ticket }) {
  return ticket.sla_state && ticket.minutes_left !== null ? (
    <SlaClock state={ticket.sla_state} minutesLeft={ticket.minutes_left} usedPercent={ticket.used_percent} dueAt={ticket.due_at} />
  ) : (
    <span className="text-muted-foreground">No SLA clock</span>
  );
}

type Runbook = { id: string; title: string; application: string | null; markdown: string };

/** One runbook line with its **bold**, *italic* and `code` shown as such. */
function inline(line: string) {
  return line.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/).map((part, i) =>
    i % 2 === 0 ? (
      part
    ) : part.startsWith("**") ? (
      <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
    ) : part.startsWith("`") ? (
      <code key={i} className="rounded bg-muted px-1 font-mono text-[0.9em]">{part.slice(1, -1)}</code>
    ) : (
      <em key={i}>{part.slice(1, -1)}</em>
    ),
  );
}

const BULLET = /^- /;
const NUMBER = /^\d+\. /;

/** A runbook section as text: paragraphs, bullet lists and numbered steps.
 *  shortcut: only the markdown the runbooks use (no tables, links or nested lists); a markdown library when they need more. */
function RunbookText({ markdown }: { markdown: string }) {
  const lines = markdown.split("\n").filter((line) => line.trim() && line.trim() !== "---");
  const blocks: React.ReactNode[] = [];
  for (let i = 0; i < lines.length; ) {
    const marker = [BULLET, NUMBER].find((m) => m.test(lines[i]));
    if (!marker) {
      const heading = /^\*\*[^*]+\*\*$/.test(lines[i]); // "**Symptoms**" on its own line
      blocks.push(<p key={i} className={heading ? "mt-2 first:mt-0" : undefined}>{inline(lines[i])}</p>);
      i++;
      continue;
    }
    const start = i;
    while (i < lines.length && marker.test(lines[i])) i++;
    const items = lines.slice(start, i).map((line, n) => <li key={n}>{inline(line.replace(marker, ""))}</li>);
    blocks.push(
      marker === BULLET ? (
        <ul key={start} className="flex list-disc flex-col gap-1 pl-5">{items}</ul>
      ) : (
        <ol key={start} className="flex list-decimal flex-col gap-1 pl-5">{items}</ol>
      ),
    );
  }
  return <div className="flex flex-col gap-2 break-words">{blocks}</div>;
}

/** A runbook id that opens the runbook over the page: a persona may only open the pages in their menu. */
function RunbookButton({ id, label }: { id: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const [runbook, setRunbook] = useState<Runbook | null>(null);
  const [failed, setFailed] = useState(false);

  const show = () => {
    setOpen(true);
    if (runbook) return;
    setFailed(false);
    apiClient<Runbook>(`/runbooks/${encodeURIComponent(id)}`)
      .then(setRunbook)
      .catch(() => setFailed(true));
  };

  return (
    <>
      {label ? (
        <Button variant="secondary" onClick={show}>
          {label}
        </Button>
      ) : (
        <Button variant="link" size="xs" className="px-0 font-mono text-foreground underline" onClick={show}>
          {id}
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{runbook?.title ?? id}</DialogTitle>
            <DialogDescription>
              {runbook
                ? [runbook.id, runbook.application, "from the knowledge base"].filter(Boolean).join(" · ")
                : failed
                  ? "This runbook could not be opened. Close this and try again in a moment."
                  : "Loading…"}
            </DialogDescription>
          </DialogHeader>
          {runbook && <RunbookText markdown={runbook.markdown} />}
          {!runbook && !failed && (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4" />
              <Skeleton className="h-4" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
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
      return a.actor ? `${a.actor} sent the agents' summary for ${on} to Jira.` : `The agents' summary for ${on} was sent to Jira.`;
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
    case "sync_failed":
      return `Jira sync failed. ${(a.error ?? "").slice(0, 160)}`;
    default:
      return null;
  }
}

/** Today's events, newest first; `person` keeps those on their tickets. Nothing is shown when there are none. */
function ActivityCard({ title, person, asOf }: { title: string; person?: string; asOf: Board }) {
  const [items, setItems] = useState<Activity[]>([]);

  // `asOf` is the board: the activity is read again whenever the board is.
  useEffect(() => {
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    const who = person ? `&person=${encodeURIComponent(person)}` : "";
    let stale = false; // a slower answer for an earlier viewer must not replace this one
    apiClient<Activity[]>(`/personas/activity?limit=8&since=${encodeURIComponent(midnight.toISOString())}${who}`)
      .then((a) => !stale && setItems(a))
      .catch(() => !stale && setItems([])); // also a backend from before this endpoint: the card stays away
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

/** Today's agent numbers, as the admin dashboard counts them (GET /dashboard/summary); a figure with nothing behind it is left out. */
function AgentsToday({ asOf }: { asOf: Board }) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  useEffect(() => {
    dashboardService
      .getSummary()
      .then(setSummary)
      .catch(() => setSummary(null));
  }, [asOf]);
  if (!summary) return null;

  const { data_quality: dq, triage } = summary.agents;
  const reviews = summary.agreement;
  const prioritised = Object.entries(triage.by_verdict).reduce((n, [verdict, c]) => (verdict.startsWith("P") ? n + c : n), 0);
  const figures = [
    dq.checked > 0 && {
      value: dq.checked,
      label: "checked by Data Quality today",
      detail: `${dq.by_verdict.passed ?? 0} complete · ${dq.by_verdict.needs_info ?? 0} need details`,
    },
    triage.checked > 0 && {
      value: prioritised,
      label: "given a priority by Triage today",
      detail: `${triage.model_used} needed the model`,
    },
    reviews.reviewed > 0 && {
      value: `${Math.round(reviews.agreement * reviews.reviewed)} of ${reviews.reviewed}`,
      label: "recommendations agreed",
      detail: `Reviewed by engineers, last ${reviews.days} days`,
    },
  ].filter((f) => !!f);
  if (figures.length === 0) return null;
  return (
    <Card className="gap-0 py-0">
      <SectionHead title="What the agents did" />
      <dl className="grid sm:grid-cols-3">
        {figures.map((f) => (
          <div key={f.label} className="flex flex-col gap-0.5 px-4 py-3">
            <dt className="text-[13px]">
              <span className="text-xl font-semibold tabular-nums">{f.value}</span> {f.label}
            </dt>
            <dd className="text-xs text-muted-foreground">{f.detail}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

const never = () => () => {};
const thisHour = () => new Date().setMinutes(0, 0, 0);

/**
 * The home of everyone who works tickets, from one board. With `mine` it is the viewer's own tickets (engineer);
 * without, every open ticket (lead), who also sees who has what: every difference hangs on `lead` below.
 * With `worklist` it is the page after it: the viewer's own tickets as a list, without the summary.
 */
export function PersonaOverview({ mine, worklist }: { mine?: boolean; worklist?: boolean }) {
  const viewer = usePerson();
  const person = mine ? viewer : undefined;
  const lead = !mine;
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<PipelineTicket | null>(null);
  const [query, setQuery] = useState("");
  const [app, setApp] = useState("");
  const [group, setGroup] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [running, setRunning] = useState(false);
  const [ran, setRan] = useState<string | null>(null);
  // The clock is read in the browser only: prerendered, the greeting and date would be the build's.
  const hour = useSyncExternalStore(never, thisHour, () => null);
  const now = hour === null ? null : new Date(hour);

  // Only the newest request may fill the page: while the page hydrates the viewer is briefly the default
  // persona, and that first answer can arrive after the real viewer's and show someone else's tickets.
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
          : `Data Quality checked ${dq.evaluated}, Triage set a priority on ${triage.evaluated}.`) +
          (failed ? ` The model failed on ${failed}.` : "")
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
  const toAssign = (ticket: Ticket) => lead && !ticket.assignee;
  const ready = tickets.filter((ticket) => ticket.priority_from === "reviewed");
  const hero = worklist ? undefined : ready.at(0);
  const toReview = tickets.filter((ticket) => ticket.stage === "triaged");
  const waiting = tickets.filter((ticket) => ticket.stage === "awaiting_info");
  const upNext = tickets.filter((ticket) => ticket !== hero && ticket.stage !== "awaiting_info");

  // The board has no description; without this call the card only lacks its description and badges.
  const heroId = hero?.id;
  useEffect(() => {
    if (!heroId) return;
    apiClient<PipelineTicket>(`/tickets/${encodeURIComponent(heroId)}`)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [heroId, board]);
  const shown = detail?.id === heroId ? detail : null;
  // Everything from the "Reported by" line on is dropped: that line can carry an unmasked personal name.
  const description = shown?.description.split(/^\s*reported by/im)[0].trim();
  const found = (shown?.agent_runs.findLast((r) => r.agent === "triage")?.output ?? {}) as {
    rule?: string | null;
    signals?: { scope?: string | null; tier?: number | null } | null;
  };

  const onTime = !!t && t.sla_breached + t.sla_at_risk === 0;
  const wrong = [
    t?.sla_breached && `${count(t.sla_breached, "ticket has", "tickets have")} breached SLA`,
    t?.sla_at_risk && `${count(t.sla_at_risk, "ticket is", "tickets are")} close to breach`,
    lead && t?.unassigned && `${count(t.unassigned, "ticket has", "tickets have")} no engineer`,
  ].filter((part): part is string => !!part);
  // The ticket whose SLA is due first, or is the most overdue.
  const nearest = tickets.reduce<Ticket | null>(
    (first, ticket) => (ticket.minutes_left !== null && (!first || ticket.minutes_left < first.minutes_left!) ? ticket : first),
    null
  );
  const withClock = toReview.filter((ticket) => ticket.minutes_left !== null).length;
  const drafted = waiting.filter((ticket) => ticket.has_draft).length;
  const hasRunbooks = tickets.some((ticket) => ticket.runbook !== undefined); // false on a backend from before the field
  const n = (v: number) => (board ? v : error ? "—" : <Skeleton className="h-7 w-10" />);

  // A pressed priority tile lists every ticket it counts, also the one in the card above and those waiting on the reporter.
  const chosen = GROUPS.find((g) => g.key === group && tickets.some(g.has)); // a tile that emptied is no longer pressed
  const base = chosen ? tickets.filter(chosen.has) : upNext;
  const apps = [...base.reduce((counts, ticket) => counts.set(appOf(ticket), (counts.get(appOf(ticket)) ?? 0) + 1), new Map<string, number>())].sort(
    (a, b) => b[1] - a[1]
  );
  const q = query.trim().toLowerCase();
  const last = Number.MAX_SAFE_INTEGER;
  const listed = base
    .filter(
      (ticket) =>
        (!app || appOf(ticket) === app) &&
        (!q || [ticket.id, ticket.summary, ticket.application, ticket.assignee].some((v) => v?.toLowerCase().includes(q)))
    )
    .sort((a, b) => (a.priority ?? last) - (b.priority ?? last) || (a.minutes_left ?? last) - (b.minutes_left ?? last));
  const pages = Math.ceil(listed.length / PAGE_SIZE) || 1;
  const current = Math.min(page, pages); // a refresh can leave fewer pages than the one being looked at

  return (
    <AppShell>
      <PageHeader
        title={
          worklist
            ? "My worklist"
            : now
            ? `Good ${now.getHours() < 12 ? "morning" : now.getHours() < 18 ? "afternoon" : "evening"}, ${viewer.split(" ")[0]}`
            : " "
        }
        context={
          !t || !now
            ? error
              ? undefined
              : (
                <>
                  <span className="sr-only">Loading…</span>
                  <Skeleton className="mt-1 h-3.5 w-72 max-w-full" />
                </>
              )
            : `${now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })} · ${count(t.open, "open ticket", "open tickets")}` +
              (lead ? `${t.unassigned ? ` · ${t.unassigned} with no engineer` : ""} · engineers are assigned in Jira` : " assigned to you in Jira")
        }
        actions={
          <>
            {/* `now`: not in the prerendered page, which every persona is served before the browser knows who they are. */}
            {lead && now && (
              <Button onClick={runAgents} disabled={running}>
                <Play />
                {running ? "Running…" : "Run agents"}
              </Button>
            )}
            <Button variant="secondary" onClick={load}>Refresh</Button>
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
              {onTime &&
                (lead
                  ? ` No P1 or P2 is breached or close to breach${wrong.length ? "." : ", and every open ticket has an engineer."}`
                  : t.p1_p2 > 1 && ` None of your ${t.p1_p2} P1 and P2 tickets is breached or close to breach.`)}
              {nearest &&
                (nearest.minutes_left! < 0
                  ? ` The most overdue is ${span(nearest.minutes_left!)} over.`
                  : ` The nearest deadline is ${nearest.due_at ? dueWords(nearest.due_at) : `in ${span(nearest.minutes_left!)}`}.`)}
            </span>
          </Status>
        </p>
      )}

      {tickets.length > 0 && (
        <section aria-labelledby="queue" className="flex flex-col gap-2">
          <h2 id="queue" className="text-xl font-semibold tabular-nums">
            {count(tickets.length, "ticket", "tickets")} in {mine ? "your queue" : "the team's queue"}
          </h2>
          <div className="flex flex-wrap gap-2">
            {GROUPS.map((g) => ({ ...g, n: tickets.filter(g.has).length }))
              .filter((g) => g.n > 0)
              .map((g) => (
                <Button
                  key={g.key}
                  variant="secondary"
                  aria-pressed={group === g.key}
                  onClick={() => {
                    setGroup(group === g.key ? null : g.key);
                    setApp("");
                    setPage(1);
                  }}
                  className={cn(
                    "h-auto min-w-28 flex-col items-start gap-0 rounded-[14px] px-4 py-2.5",
                    g.look,
                    group === g.key && "ring-2 ring-foreground ring-offset-2 ring-offset-background"
                  )}
                >
                  <span className="text-2xl leading-8 tabular-nums">
                    <CountUp value={g.n} />
                  </span>
                  <span className="text-xs font-medium">{g.label}</span>
                </Button>
              ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {chosen ? `The table lists the ${chosen.label} tickets. Press the tile again for all of them.` : "Press a tile to list only those tickets."}
          </p>
        </section>
      )}

      {hero && (
        <Card className="gap-4 px-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <p className="text-xs font-medium text-muted-foreground">{mine ? "Work on this now" : "Most urgent ticket ready to work"}</p>
            <h2 className="flex flex-wrap items-center gap-2 text-base font-semibold">
              <PriorityChip priority={hero.priority} />
              {hero.summary || "No summary"}
            </h2>
            <p className="text-xs text-muted-foreground">
              <span className="font-mono">{hero.id}</span> · {appOf(hero)}
              {lead && ` · ${hero.assignee ?? NO_ENGINEER}`} · P{hero.priority} confirmed in review
              {toAssign(hero) && ` · ${nextStep(hero, true)}`}
            </p>
            {description && <p className="whitespace-pre-line">{description}</p>}
            {(found.rule || found.signals) && (
              <div className="flex flex-wrap gap-1.5">
                {found.signals?.scope === "wide" && <Badge variant="secondary">Wide impact</Badge>}
                {found.signals?.tier != null && <Badge variant="secondary">Tier {found.signals.tier} application</Badge>}
                {found.rule && (
                  <Badge variant="secondary">
                    Rule <span className="font-mono">{found.rule}</span>
                  </Badge>
                )}
              </div>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              {hero.url && (
                <Button nativeButton={false} render={<a href={hero.url} target="_blank" rel="noreferrer" />}>
                  {toAssign(hero) ? "Assign in Jira" : "Open in Jira"}
                </Button>
              )}
              {hero.runbook && <RunbookButton id={hero.runbook} label={`Open runbook ${hero.runbook}`} />}
              <Button variant="secondary" nativeButton={false} render={<Link href={ticketHref(hero)} />}>
                See the ticket
              </Button>
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

      {!worklist && (
        <div className="grid gap-4 sm:grid-cols-3">
          <StatTile
            label="Ready to work"
            href={mine ? "/my-tickets" : undefined}
            value={n(ready.length)}
            window={
              !board
                ? undefined
                : ready.length === 0
                  ? "No priority confirmed yet"
                  : ready.length === 1
                    ? "Priority confirmed. It is the ticket above."
                    : "Priority confirmed. The most at risk is above."
            }
          />
          <StatTile
            label={mine ? "Waiting for your priority review" : "Waiting for a priority review"}
            value={n(toReview.length)}
            window={board ? `${withClock} ${withClock === 1 ? "has" : "have"} an SLA clock running` : undefined}
            href="/review"
          />
          <StatTile
            label="Waiting on the reporter"
            href={mine ? "/my-tickets" : undefined}
            value={n(waiting.length)}
            window={!board ? undefined : drafted ? `Details are missing. ${count(drafted, "reply is", "replies are")} drafted.` : "Details are missing from the ticket"}
          />
        </div>
      )}

      {lead && board && <AgentsToday asOf={board} />}

      {!board ? (
        error ? null : (
          <Card aria-busy="true">
            <span className="sr-only">Loading tickets…</span>
            <div className="flex flex-col gap-3 px-4">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-5" />
              ))}
            </div>
          </Card>
        )
      ) : tickets.length === 0 ? (
        <Card>
          <p className="px-4 text-muted-foreground">{mine ? `Nothing open is assigned to ${viewer} in Jira.` : "No open tickets."}</p>
        </Card>
      ) : null}

      {base.length > 0 && (
        <Card className="gap-0 py-0">
          <SectionHead title={`${chosen ? `${chosen.label} tickets` : worklist ? "Tickets with a priority" : "Up next"} · ${base.length}`}>
            <span className="text-xs text-muted-foreground">
              Agree with the priority or change it, then work the ticket in Jira · highest priority first, then the nearest deadline
            </span>
          </SectionHead>
          <div className="flex flex-wrap gap-2 border-b border-border px-4 py-3">
            <div className="relative flex-[2_1_18rem]">
              <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
              <Input
                aria-label="Search the tickets up next"
                placeholder={`Search by ticket ID, summary${lead ? ", application or engineer" : " or application"}`}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(1);
                }}
                className="pl-8"
              />
            </div>
            <div className="flex-[1_1_12rem]">
              <select
                aria-label="Application"
                value={app}
                onChange={(e) => {
                  setApp(e.target.value);
                  setPage(1);
                }}
                className={SELECT}
              >
                <option value="">All applications ({base.length})</option>
                {apps.map(([name, c]) => (
                  <option key={name} value={name}>
                    {name} ({c})
                  </option>
                ))}
              </select>
            </div>
          </div>
          {listed.length === 0 ? (
            <p className="px-4 py-6 text-muted-foreground">No tickets match the search and filter.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Priority</TableHead>
                  <TableHead>Ticket</TableHead>
                  {lead && <TableHead className="hidden sm:table-cell">Engineer</TableHead>}
                  <TableHead className="hidden md:table-cell">What Triage found</TableHead>
                  {hasRunbooks && <TableHead className="hidden lg:table-cell">Runbook</TableHead>}
                  <TableHead>SLA</TableHead>
                  <TableHead className="pr-4 text-right">Next step</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {listed.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE).map((ticket) => (
                  <TableRow key={ticket.id}>
                    <TableCell className="pl-4">
                      <PriorityChip priority={ticket.priority} />
                    </TableCell>
                    <TableCell>
                      <Link href={ticketHref(ticket)} className="font-medium underline-offset-4 hover:underline">
                        {ticket.summary || "No summary"}
                      </Link>
                      <span className="block text-xs text-muted-foreground">
                        <span className="font-mono">{ticket.id}</span> · {appOf(ticket)}
                      </span>
                    </TableCell>
                    {lead && (
                      <TableCell className={ticket.assignee ? "hidden sm:table-cell" : "hidden text-muted-foreground sm:table-cell"}>
                        {ticket.assignee ?? NO_ENGINEER}
                      </TableCell>
                    )}
                    <TableCell className="hidden md:table-cell">
                      {ticket.triage_reason ?? <span className="text-muted-foreground">—</span>}
                      <span className="block text-xs text-muted-foreground">{versusReported(ticket)}</span>
                    </TableCell>
                    {hasRunbooks && (
                      <TableCell className="hidden lg:table-cell">
                        {ticket.runbook ? <RunbookButton id={ticket.runbook} /> : <span className="text-muted-foreground">None matched</span>}
                      </TableCell>
                    )}
                    <TableCell>
                      <Sla ticket={ticket} />
                    </TableCell>
                    <TableCell className="pr-4">
                      <div className="flex items-center justify-end gap-3">
                        <span className="hidden text-right text-xs text-muted-foreground xl:inline">{nextStep(ticket, toAssign(ticket))}</span>
                        {toAssign(ticket) && ticket.url ? (
                          <Button variant="secondary" size="sm" nativeButton={false} render={<a href={ticket.url} target="_blank" rel="noreferrer" />}>
                            Assign
                          </Button>
                        ) : (
                          <Button variant="secondary" size="sm" nativeButton={false} render={<Link href={ticketHref(ticket)} />}>
                            {ticket.stage === "triaged" ? "Review" : "Open"}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {listed.length > PAGE_SIZE && (
            <div className="flex flex-col items-center justify-between gap-3 border-t border-border px-4 py-3 sm:flex-row">
              <span className="text-xs text-muted-foreground tabular-nums">
                Showing {(current - 1) * PAGE_SIZE + 1} to {Math.min(current * PAGE_SIZE, listed.length)} of {listed.length} tickets
                {listed.length !== base.length && ` (filtered from ${base.length})`}
              </span>
              <div className="flex items-center gap-2">
                <Button variant="secondary" size="sm" disabled={current <= 1} onClick={() => setPage(current - 1)}>
                  <ChevronLeft />
                  Previous
                </Button>
                <span className="px-2 text-xs font-medium tabular-nums">
                  Page {current} of {pages}
                </span>
                <Button variant="secondary" size="sm" disabled={current >= pages} onClick={() => setPage(current + 1)}>
                  Next
                  <ChevronRight />
                </Button>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* One card fills the row, two sit side by side, and of three the first fills the row. */}
      <div className="grid items-start gap-4 lg:grid-cols-2 lg:[&>*:first-child:nth-last-child(odd)]:col-span-full">
        {waiting.length > 0 && (
          <Card className="gap-0 py-0">
            <SectionHead title={`Waiting on the reporter · ${waiting.length}`} />
            <ul role="list">
              {waiting.map((ticket) => (
                <ListRow
                  key={ticket.id}
                  title={
                    <Link href={ticketHref(ticket)} className="underline-offset-4 hover:underline">
                      {ticket.summary || "No summary"}
                    </Link>
                  }
                  meta={
                    <span>
                      <span className="font-mono">{ticket.id}</span>
                      {lead && ` · ${ticket.assignee ?? nextStep(ticket, true)}`}
                      {!!ticket.missing?.length &&
                        ` · missing ${and.format(ticket.missing.map((m) => MISSING_WORDS[m] ?? m.replaceAll("_", " ")))}`}
                    </span>
                  }
                  actions={
                    ticket.has_draft && (
                      <Button variant="secondary" size="sm" nativeButton={false} render={<Link href={ticketHref(ticket)} />}>
                        See the draft
                      </Button>
                    )
                  }
                />
              ))}
            </ul>
            <p className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
              These get a priority and an SLA clock once the reporter answers.
            </p>
          </Card>
        )}

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
                  <TableHead className="pr-4 text-right">Waiting for review</TableHead>
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

        {board && !worklist && <ActivityCard title={mine ? "Activity on your tickets · today" : "Recent activity · today"} person={person} asOf={board} />}
      </div>
    </AppShell>
  );
}
