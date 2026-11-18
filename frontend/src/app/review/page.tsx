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
import { pipelineService } from "@/services/pipeline-service";
import { FLAGS, ReviewQueueItem } from "@/types/pipeline";

/** Recommendations waiting for an engineer: flagged ones first, then the most urgent. */
export default function ReviewPage() {
  const [items, setItems] = useState<ReviewQueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      pipelineService
        .reviewQueue()
        .then((q) => {
          setItems(q);
          setError(null);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load the review queue")),
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
            ? `${items.length} ${items.length === 1 ? "recommendation" : "recommendations"} waiting. Agree, or change the priority and say why: the answers show where the rules need fixing.`
            : "Recommendations waiting for an engineer."
        }
      />
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {items && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile variant="primary" label="Waiting for a decision" value={items.length} />
          <StatTile label="P1 and P2" value={items.filter((i) => i.recommended_priority <= 2).length} window="recommended by Triage" />
          <StatTile label="Flagged" value={items.filter((i) => i.flags.length > 0).length} window="shown first" />
          <StatTile label="Priority would change" value={items.filter((i) => i.reported_priority !== null && i.reported_priority !== i.recommended_priority).length} window="against the reported one" />
        </div>
      )}
      <Card className="gap-0 py-0">
        {!items ? (
          !error && <p className="px-4 py-3 text-[13px] text-muted-foreground">Loading…</p>
        ) : items.length === 0 ? (
          <p className="px-4 py-3 text-[13px] text-muted-foreground">Nothing is waiting. New recommendations appear here after Triage runs.</p>
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
                      {[i.application, i.reported_priority && `reporter asked for P${i.reported_priority}`].filter(Boolean).join(" · ")}
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
