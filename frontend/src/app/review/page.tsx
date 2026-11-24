"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { ListRow } from "@/components/console/list-row";
import { PriorityChip } from "@/components/console/priority-chip";
import { ReviewActions } from "@/components/console/review-actions";
import { StatTile } from "@/components/console/stat-tile";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useViewAs } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { FLAGS, ReviewQueueItem, TicketListItem } from "@/types/pipeline";

/** Recommendations waiting for an engineer: flagged ones first, then the most urgent. */
export default function ReviewPage() {
  const [items, setItems] = useState<ReviewQueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Closure notes an engineer submitted: the lead approves them or sends them back (LEAD_REVIEW).
  const role = useViewAs();
  const lead = role === "lead" || role === "admin";
  const [notes, setNotes] = useState<TicketListItem[] | null>(null);
  useEffect(() => {
    if (lead) pipelineService.listByStage("in_review").then((r) => setNotes(r.items), () => setNotes([]));
  }, [lead]);

  const load = useCallback(
    () =>
      pipelineService
        .reviewQueue()
        .then((q) => {
          setItems(q);
          setError(null);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load the review queue. Try again.")),
    []
  );
  useEffect(() => {
    load();
  }, [load]);

  return (
    <AppShell>
      <PageHeader
        title="Review queue"
        context={
          items
            ? `${items.length} ${items.length === 1 ? "recommendation" : "recommendations"} awaiting review. Accept the priority, or change it and give a reason: your decisions show where the rules need tuning.`
            : "Priority recommendations awaiting engineer review."
        }
      />
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {items && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile variant="primary" label="Awaiting decision" value={items.length} />
          <StatTile label="P1 and P2" value={items.filter((i) => i.recommended_priority <= 2).length} window="recommended by Triage" />
          <StatTile label="Flagged" value={items.filter((i) => i.flags.length > 0).length} window="shown first" />
          <StatTile label="Priority change proposed" value={items.filter((i) => i.reported_priority !== null && i.reported_priority !== i.recommended_priority).length} window="compared with the requested priority" />
        </div>
      )}
      {lead && notes && notes.length > 0 && (
        <Card className="gap-0 py-0">
          <h2 className="border-b border-border px-4 py-3 text-sm font-semibold">Closure notes waiting for your review · {notes.length}</h2>
          <ul role="list">
            {notes.map((t) => (
              <ListRow
                key={t.id}
                lead={t.reported_priority ? <PriorityChip priority={t.reported_priority} /> : undefined}
                itemKey={t.id}
                title={t.summary}
                meta={[t.application, t.source].filter(Boolean).join(" · ")}
                actions={
                  <Button size="sm" nativeButton={false} render={<Link href={`/tickets/${encodeURIComponent(t.id)}`} />}>
                    Review closure note
                  </Button>
                }
              />
            ))}
          </ul>
        </Card>
      )}
      <Card className="gap-0 py-0">
        {!items ? (
          !error && <p className="px-4 py-3 text-[13px] text-muted-foreground">Loading…</p>
        ) : items.length === 0 ? (
          <p className="px-4 py-3 text-[13px] text-muted-foreground">No items awaiting review. New recommendations appear here after Triage runs.</p>
        ) : (
          <ul role="list">
            {items.map((i) => (
              <ListRow
                key={i.ticket_id}
                lead={<PriorityChip priority={i.recommended_priority} />}
                itemKey={
                  <Link href={`/tickets/${encodeURIComponent(i.ticket_id)}`} className="underline-offset-4 hover:underline">
                    {i.ticket_id}
                  </Link>
                }
                title={i.summary}
                meta={
                  <>
                    <span>
                      {[i.application, i.reported_priority && `requester asked for P${i.reported_priority}`].filter(Boolean).join(" · ")}
                    </span>
                    {i.flags.map((f) => (
                      <Badge key={f}>{FLAGS[f] ?? f}</Badge>
                    ))}
                    <span className="basis-full break-words">{i.reason}</span>
                  </>
                }
                actions={<ReviewActions ticketId={i.ticket_id} recommended={i.recommended_priority} onDone={load} />}
              />
            ))}
          </ul>
        )}
      </Card>
    </AppShell>
  );
}
