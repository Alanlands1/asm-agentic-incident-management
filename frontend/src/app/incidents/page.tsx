"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { PriorityChip } from "@/components/console/priority-chip";
import { StatTile } from "@/components/console/stat-tile";
import { SectionHead, SlaClock, span } from "@/components/console/sync-parts";
import { Card } from "@/components/ui/card";
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
      setError(e instanceof Error ? e.message : "Couldn't declare the major incident");
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
  const left = item.first_message.minutes_left;
  const id = `msg-${item.ticket_id}`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setError("Couldn't copy. Select the text and copy it by hand.");
    }
  };
  const markSent = async (toJira: boolean) => {
    setBusy(toJira ? "jira" : "sent");
    setError(null);
    try {
      await incidentService.markSent(item.ticket_id, text, person, toJira);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : toJira ? "Couldn't post to Jira" : "Couldn't record the message");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={id} className="text-xs font-medium text-muted-foreground">
          {item.last_sent ? "Next update to the people on the ticket" : "First message to the people on the ticket"}
        </label>
        {item.last_sent ? (
          <span className="inline-flex items-center gap-1.5 text-xs">
            <CircleCheck className="size-4" aria-hidden="true" />
            Sent by {item.last_sent.sent_by} at {time(item.last_sent.sent_at)}
          </span>
        ) : (
          <span className={left < 0 ? "text-xs font-semibold text-primary" : "text-xs"}>
            Send by {time(item.first_message.send_by)} ({left < 0 ? `${span(left)} late` : `${span(left)} left`})
          </span>
        )}
      </div>
      <Textarea id={id} rows={3} value={text} onChange={(e) => { setText(e.target.value); setCopied(false); }} />
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={copy}>
          <Copy />
          {copied ? "Copied" : "Copy"}
        </Button>
        {item.can_post_to_jira && (
          <Button onClick={() => markSent(true)} disabled={busy !== null || !text.trim()}>
            <Send />
            {busy === "jira" ? "Posting…" : "Post to Jira"}
          </Button>
        )}
        <Button
          variant={item.can_post_to_jira ? "secondary" : "default"}
          onClick={() => markSent(false)}
          disabled={busy !== null || !text.trim()}
        >
          {busy === "sent" ? "Saving…" : "Mark as sent"}
        </Button>
      </div>
    </div>
  );
}

/** Admin and lead: storms and P1/P2 tickets that need a person now. A person declares and sends (Post to Jira adds the comment for them); nothing goes out by itself. */
const TicketLink = ({ id }: { id: string }) => (
  <Link href={`/tickets/${encodeURIComponent(id)}`} className="font-mono underline-offset-4 hover:underline">
    {id}
  </Link>
);

export default function IncidentsPage() {
  const { data, error, refresh } = useAttention();
  const waiting = data?.p1_p2.filter((i) => !i.last_sent).length ?? 0;

  return (
    <AppShell>
      <PageHeader
        title="Incidents"
        context={
          data
            ? `${plural(data.storms.length, "storm", "storms")} · ${plural(data.p1_p2.length, "open P1/P2", "open P1/P2s")} · ${waiting} whose reporter has heard nothing yet`
            : "Loading…"
        }
        actions={<Button variant="secondary" onClick={refresh}>Refresh</Button>}
      />

      {data && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile variant="primary" label="Storms now" value={data.storms.length} window={data.storms[0]?.application ?? "none open"} />
          <StatTile label="Open P1" value={data.p1_p2.filter((i) => i.priority === 1).length} />
          <StatTile label="Open P2" value={data.p1_p2.filter((i) => i.priority === 2).length} />
          <StatTile label="Past SLA now" value={data.p1_p2.filter((i) => i.state === "breached").length} window={`${waiting} whose reporter has heard nothing yet`} />
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
          Nothing needs attention. Storms and P1/P2 tickets show here as Triage finds them.
        </Card>
      )}

      {data && data.storms.length > 0 && (
        <Card className="gap-0 py-0">
          <SectionHead title="Storms">
            <span className="text-xs text-muted-foreground">Many people reporting the same issue at once</span>
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
            <span className="text-xs text-muted-foreground">Most at risk first</span>
          </SectionHead>
          <ul role="list">
            {data.p1_p2.map((i) => (
              <li key={i.ticket_id} className="flex flex-col gap-3 border-b border-border px-4 py-3 last:border-b-0">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <PriorityChip priority={`${i.priority}`} />
                    <div className="min-w-0">
                      <p className="break-words font-semibold">
                        <span className="mr-2 text-xs font-normal text-muted-foreground">
                          <TicketLink id={i.ticket_id} />
                        </span>
                        {i.summary || "No summary"}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {[
                          i.application ?? "No application",
                          i.priority_from === "reviewed" ? "priority set by an engineer" : "priority recommended by Triage",
                          i.storm_id ? `part of storm ${i.storm_id}` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    </div>
                  </div>
                  <SlaClock state={i.state} minutesLeft={i.minutes_left} usedPercent={i.used_percent} />
                </div>
                <FirstMessage key={i.last_sent?.id ?? "draft"} item={i} onDone={refresh} />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </AppShell>
  );
}
