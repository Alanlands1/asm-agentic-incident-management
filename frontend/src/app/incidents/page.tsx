"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import { StatTile } from "@/components/console/stat-tile";
import { SectionHead, SlaClock, span } from "@/components/console/sync-parts";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { SELECT } from "@/components/console/assign-control";
import { useAttention } from "@/hooks/use-attention";
import { usePerson } from "@/lib/view-as";
import { incidentService } from "@/services/incident-service";
import { AttentionItem, Storm } from "@/types/incident";
import { CircleCheck, Copy, Send, Siren, TriangleAlert } from "lucide-react";

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const when = (iso: string) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function DeclareButton({ storm, onDone }: { storm: Storm; onDone: () => void }) {
  const person = usePerson();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const declare = async () => {
    setBusy(true);
    setError(null);
    try {
      await incidentService.declare(storm.id, person);
      setOpen(false);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't declare the major incident. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button onClick={() => setOpen(true)}>Declare major incident</Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Declare a major incident?</DialogTitle>
          <DialogDescription>
            {storm.application ?? "Several applications"}: {plural(storm.people, "person", "people")} reported it in{" "}
            {plural(storm.ticket_count, "ticket", "tickets")}. This records that you, {person}, declared it. Nothing is sent.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <DialogClose render={<Button variant="secondary" />}>Cancel</DialogClose>
          <Button onClick={declare} disabled={busy}>
            {busy ? "Declaring…" : "Declare major incident"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FirstMessage({ item, onDone }: { item: AttentionItem; onDone: () => void }) {
  const person = usePerson();
  const [text, setText] = useState(item.last_sent?.text ?? item.first_message.text);
  const [busy, setBusy] = useState<"jira" | "sent" | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const left = item.first_message.minutes_left;
  const id = `msg-${item.ticket_id}`;
  const auto = item.auto_send ?? false;
  const nextAt = item.next_update_at ?? null;
  const late = !item.last_sent && !auto && left < 0;
  const shown = auto ? (item.last_sent?.text ?? item.first_message.text) : text;
  const status = item.last_sent
    ? [`Last sent ${time(item.last_sent.sent_at)} by ${item.last_sent.sent_by}`, ...(nextAt ? [`Next update ${time(nextAt)}`] : [])]
    : auto
      ? [left < 0 ? "Sending now" : `Sends automatically by ${time(item.first_message.send_by)}`]
      : [`Send by ${time(item.first_message.send_by)} (${left < 0 ? `${span(left)} late` : `${span(left)} left`})`];
  // the card's one line; the dialog shows the full status
  const brief = item.last_sent
    ? `Sent ${time(item.last_sent.sent_at)}${nextAt ? ` · next ${time(nextAt)}` : ""}`
    : status[0];

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shown);
      setCopied(true);
    } catch {
      setError("Couldn't copy. Select the text and copy it manually.");
    }
  };
  const markSent = async (toJira: boolean) => {
    setBusy(toJira ? "jira" : "sent");
    setError(null);
    try {
      await incidentService.markSent(item.ticket_id, text, person, toJira);
      setOpen(false);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : toJira ? "Couldn't post to Jira. Try again." : "Couldn't record the message. Try again.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">Stakeholder updates</span>
        {item.last_sent ? (
          <Badge variant="secondary">
            <CircleCheck aria-hidden="true" />
            Sent
          </Badge>
        ) : auto ? (
          <Badge variant="outline">Scheduled</Badge>
        ) : (
          <Badge variant="destructive">Waiting for a person</Badge>
        )}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <div className="flex items-center justify-between gap-2">
          <p className={late ? "min-w-0 break-words text-xs font-semibold text-primary" : "min-w-0 break-words text-xs"}>{brief}</p>
          <Button variant="secondary" size="sm" className="shrink-0" onClick={() => setOpen(true)}>
            View
          </Button>
        </div>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Update to stakeholders: {item.ticket_id}</DialogTitle>
            <DialogDescription>{status.join(" · ")}</DialogDescription>
          </DialogHeader>
          {auto ? (
            <>
              <p className="whitespace-pre-wrap break-words">{shown}</p>
              <p className="text-xs text-muted-foreground">The system sends this by itself. Nothing to do here.</p>
            </>
          ) : (
            <Textarea
              id={id}
              aria-label="Update to stakeholders"
              rows={8}
              value={text}
              onChange={(e) => { setText(e.target.value); setCopied(false); }}
            />
          )}
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            {auto && <DialogClose render={<Button variant="secondary" />}>Close</DialogClose>}
            <Button variant="secondary" onClick={copy}>
              <Copy />
              {copied ? "Copied" : "Copy"}
            </Button>
            {!auto && item.can_post_to_jira && (
              <Button onClick={() => markSent(true)} disabled={busy !== null || !text.trim()}>
                <Send />
                {busy === "jira" ? "Posting…" : "Post to Jira"}
              </Button>
            )}
            {!auto && (
              <Button
                variant={item.can_post_to_jira ? "secondary" : "default"}
                onClick={() => markSent(false)}
                disabled={busy !== null || !text.trim()}
              >
                {busy === "sent" ? "Saving…" : "Mark as sent"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** Admin and lead: storms and P1/P2 tickets that need a person now. A person declares and sends (Post to Jira adds the comment for them); nothing goes out by itself. */
const TicketLink = ({ id }: { id: string }) => (
  <Link href={`/tickets/${encodeURIComponent(id)}`} className="font-mono underline-offset-4 hover:underline">
    {id}
  </Link>
);

/** One cell of the P1 and P2 grid: a single ticket, or a whole storm shown through one of its tickets. */
interface AttentionCard {
  item: AttentionItem;
  stormId: number | null;
  /** How many tickets the cell stands for (1 for a single ticket). */
  tickets: number;
  /** The tickets the cell stands for besides `item`. */
  others: string[];
}

/** Tickets of one storm become one card, placed where the storm's first ticket was. It shows the main ticket, or the most at-risk one when the main ticket is not P1/P2. */
function toCards(items: AttentionItem[], storms: Storm[]): AttentionCard[] {
  const cards: AttentionCard[] = [];
  const byStorm = new Map<number, AttentionCard>();
  const collapsed = new Map<number, string[]>();
  for (const i of items) {
    if (i.storm_id == null) {
      cards.push({ item: i, stormId: null, tickets: 1, others: [] });
      continue;
    }
    const card = byStorm.get(i.storm_id);
    if (!card) {
      const first = { item: i, stormId: i.storm_id, tickets: 1, others: [] };
      byStorm.set(i.storm_id, first);
      collapsed.set(i.storm_id, [i.ticket_id]);
      cards.push(first);
      continue;
    }
    collapsed.get(i.storm_id)?.push(i.ticket_id);
    if (storms.some((s) => s.id === i.storm_id && s.main_ticket_id === i.ticket_id)) card.item = i;
  }
  for (const [id, card] of byStorm) {
    const storm = storms.find((s) => s.id === id);
    const ids = storm?.ticket_ids ?? collapsed.get(id) ?? [];
    card.others = ids.filter((t) => t !== card.item.ticket_id);
    card.tickets = storm?.ticket_count ?? ids.length;
  }
  return cards;
}

// Same words as SlaClock shows for each state.
const SLA_WORDS: Record<AttentionItem["state"], string> = { ok: "On track", watch: "Watch", breach_likely: "Breach likely", breached: "Breached" };
const NO_APPLICATION = "__none__";
const NO_FILTERS = { priority: "", application: "", state: "", updates: "", storms: "" };

export default function IncidentsPage() {
  const { data, error, refresh } = useAttention();
  const waiting = data?.p1_p2.filter((i) => !i.last_sent).length ?? 0;
  const [filters, setFilters] = useState(NO_FILTERS);
  const pick = (key: keyof typeof NO_FILTERS) => (e: React.ChangeEvent<HTMLSelectElement>) =>
    setFilters((f) => ({ ...f, [key]: e.target.value }));
  const cards = toCards(data?.p1_p2 ?? [], data?.storms ?? []);
  const applications = [...new Set(cards.map((c) => c.item.application ?? NO_APPLICATION))].sort((a, b) =>
    a === NO_APPLICATION ? 1 : b === NO_APPLICATION ? -1 : a.localeCompare(b),
  );
  // An application that left the list after a refresh stops filtering.
  const application = applications.includes(filters.application) ? filters.application : "";
  const filtering = Boolean(filters.priority || application || filters.state || filters.updates || filters.storms);
  const shown = cards.filter(
    ({ item, stormId }) =>
      (!filters.priority || `${item.priority}` === filters.priority) &&
      (!application || (item.application ?? NO_APPLICATION) === application) &&
      (!filters.state || item.state === filters.state) &&
      (!filters.updates || (filters.updates === "sent") === Boolean(item.last_sent)) &&
      (!filters.storms || (filters.storms === "storm") === (stormId !== null)),
  );

  return (
    <AppShell>
      <PageHeader
        title="Incidents"
        context={
          data
            ? `${plural(data.storms.length, "storm", "storms")} · ${plural(data.p1_p2.length, "open P1/P2", "open P1/P2s")} · ${waiting} without a first update`
            : "Loading…"
        }
        actions={<Button variant="secondary" onClick={refresh}>Refresh</Button>}
      />

      {data && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile compact variant="primary" label="Active storms" value={data.storms.length} window={data.storms[0]?.application ?? "none open"} />
          <StatTile compact label="Open P1" value={data.p1_p2.filter((i) => i.priority === 1).length} />
          <StatTile compact label="Open P2" value={data.p1_p2.filter((i) => i.priority === 2).length} />
          <StatTile compact label="SLA breached" value={data.p1_p2.filter((i) => i.state === "breached").length} window={`${waiting} without a first update`} />
        </div>
      )}

      {error && !data && (
        <Alert variant="destructive">
          <AlertDescription>
            {error}{" "}
            <Button variant="secondary" onClick={refresh}>Try again</Button>
          </AlertDescription>
        </Alert>
      )}

      {data && data.count === 0 && data.p1_p2.length === 0 && (
        <Card className="px-4 py-6 text-muted-foreground">
          Nothing needs attention. Storms and P1/P2 tickets appear here when Triage detects them.
        </Card>
      )}

      {data && data.storms.length > 0 && (
        <Card className="gap-0 py-0">
          <SectionHead title="Storms">
            <span className="text-xs text-muted-foreground">Multiple requesters reporting the same issue at once</span>
          </SectionHead>
          <ul role="list">
            {data.storms.map((s) => (
              <li key={s.id} className="flex flex-col gap-3 border-b border-border px-4 py-3 last:border-b-0">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <Siren className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="font-semibold">
                        {s.application ?? "Several applications"}: {plural(s.people, "person", "people")} ·{" "}
                        {plural(s.ticket_count, "ticket", "tickets")}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Since {when(s.opened_at)} · last report {time(s.last_ticket_at)} · main ticket <TicketLink id={s.main_ticket_id} />
                      </p>
                      <p className="mt-1 break-words text-xs text-muted-foreground">Tickets:{" "}
                        {s.ticket_ids.map((t, n) => (
                          <Fragment key={t}>
                            {n > 0 && ", "}
                            <TicketLink id={t} />
                          </Fragment>
                        ))}
                      </p>
                    </div>
                  </div>
                  {s.status === "declared" ? (
                    <span className="inline-flex items-center gap-1.5 text-xs">
                      <TriangleAlert className="size-4" aria-hidden="true" />
                      Major incident, declared by {s.declared_by}
                      {s.declared_at && ` at ${time(s.declared_at)}`}
                    </span>
                  ) : (
                    <DeclareButton storm={s} onDone={refresh} />
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data && data.p1_p2.length > 0 && (
        <Card className="gap-0 py-0">
          <SectionHead title="P1 and P2">
            <span className="text-xs text-muted-foreground">Highest SLA risk first</span>
          </SectionHead>
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
            <select aria-label="Filter by priority" value={filters.priority} onChange={pick("priority")} className={SELECT}>
              <option value="">All priorities</option>
              <option value="1">P1</option>
              <option value="2">P2</option>
            </select>
            <select aria-label="Filter by application" value={application} onChange={pick("application")} className={SELECT}>
              <option value="">All applications</option>
              {applications.map((a) => (
                <option key={a} value={a}>{a === NO_APPLICATION ? "No application" : a}</option>
              ))}
            </select>
            <select aria-label="Filter by SLA state" value={filters.state} onChange={pick("state")} className={SELECT}>
              <option value="">All SLA states</option>
              {Object.entries(SLA_WORDS).map(([value, words]) => (
                <option key={value} value={value}>{words}</option>
              ))}
            </select>
            <select aria-label="Filter by stakeholder update" value={filters.updates} onChange={pick("updates")} className={SELECT}>
              <option value="">All updates</option>
              <option value="sent">Update sent</option>
              <option value="waiting">Update not sent</option>
            </select>
            <select aria-label="Filter by storm" value={filters.storms} onChange={pick("storms")} className={SELECT}>
              <option value="">Storms and single tickets</option>
              <option value="storm">Storms only</option>
              <option value="single">Single tickets</option>
            </select>
            {filtering && (
              <Button variant="secondary" size="sm" onClick={() => setFilters(NO_FILTERS)}>Clear</Button>
            )}
            <span className="ml-auto text-xs text-muted-foreground" aria-live="polite">
              Showing {shown.length} of {cards.length}
            </span>
          </div>
          {shown.length === 0 && <p className="px-4 py-6 text-muted-foreground">No tickets match these filters.</p>}
          <ul role="list" className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2 xl:grid-cols-4">
            {shown.map(({ item: i, stormId, tickets, others }) => (
              <li
                key={i.ticket_id}
                className={`keep-motion group flex min-w-0 transition-transform duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:z-10 hover:-translate-y-1.5 ${tickets > 1 ? "relative mr-2 mb-2" : ""}`}
              >
                {/* a storm is several tickets in one card: two card edges behind it show the stack, and fan out on hover.
                    keep-motion: the user asked for this motion to play even with reduce motion on (see globals.css) */}
                {tickets > 1 && (
                  <>
                    <Card aria-hidden="true" className="absolute inset-0 origin-bottom-left translate-x-2 translate-y-2 transition-[translate,rotate,border-color] delay-75 duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:translate-x-4 group-hover:translate-y-2.5 group-hover:rotate-3 group-hover:border-primary/60" />
                    <Card aria-hidden="true" className="absolute inset-0 origin-bottom-left translate-x-1 translate-y-1 transition-[translate,rotate,border-color] duration-500 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:translate-x-2 group-hover:translate-y-1.5 group-hover:rotate-[1.5deg] group-hover:border-primary/60" />
                  </>
                )}
                <Card size="sm" className="relative min-w-0 flex-1 gap-2 px-3 transition-[border-color,box-shadow] duration-300 group-hover:border-primary/60 group-hover:shadow-[0_14px_30px_rgba(25,29,56,0.16)]">
                  <div className="flex min-w-0 flex-col gap-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <PriorityChip priority={`${i.priority}`} />
                      <span className="min-w-0 break-all text-xs text-muted-foreground">
                        <TicketLink id={i.ticket_id} />
                      </span>
                      {tickets > 1 && others.length === 0 && (
                        <Badge variant="outline">
                          <Siren aria-hidden="true" />
                          Storm · {tickets} tickets
                        </Badge>
                      )}
                      {others.length > 0 && (
                        <Popover>
                          <PopoverTrigger render={<Button variant="secondary" size="sm" className="ml-auto" />}>
                            <Siren aria-hidden="true" />
                            {tickets} tickets
                          </PopoverTrigger>
                          <PopoverContent align="start">
                            <PopoverHeader>
                              <PopoverTitle>Other tickets in storm {stormId}</PopoverTitle>
                            </PopoverHeader>
                            <ul role="list" className="flex max-h-60 flex-col gap-1 overflow-y-auto text-xs">
                              {others.map((t) => (
                                <li key={t} className="break-all">
                                  <TicketLink id={t} />
                                </li>
                              ))}
                            </ul>
                          </PopoverContent>
                        </Popover>
                      )}
                    </div>
                    <p className="line-clamp-2 break-words font-semibold" title={i.summary}>{i.summary || "No summary"}</p>
                    <p className="break-words text-xs text-muted-foreground">
                      {[
                        i.application ?? "No application",
                        i.priority_from === "reviewed" ? "priority confirmed" : "priority recommended by Triage",
                        tickets > 1 ? `storm of ${tickets}` : stormId !== null ? `part of storm ${stormId}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <SlaClock state={i.state} minutesLeft={i.minutes_left} usedPercent={i.used_percent} />
                  <FirstMessage key={i.last_sent?.id ?? "draft"} item={i} onDone={refresh} />
                </Card>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </AppShell>
  );
}
