"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { AgentRunPanel } from "@/components/console/agent-run-panel";
import { REVIEW_EVENT } from "@/components/console/review-actions";
import { SectionHead } from "@/components/console/sync-parts";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { pipelineService } from "@/services/pipeline-service";
import { ClosureQueueItem } from "@/types/pipeline";

/** Close notes that need work and have no decision yet, worst first. */
function Queue() {
  const [items, setItems] = useState<ClosureQueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    pipelineService
      .closureQueue()
      .then(setItems)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "The queue could not be loaded"));
  }, []);
  useEffect(() => {
    load();
    window.addEventListener(REVIEW_EVENT, load); // the run panel sends it after each run or check
    return () => window.removeEventListener(REVIEW_EVENT, load);
  }, [load]);

  return (
    <Card className="gap-0 py-0">
      <SectionHead title={`Close notes that need work${items ? ` (${items.length})` : ""}`} />
      {error && (
        <Alert variant="destructive" className="m-4 w-auto">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {items?.length === 0 && <p className="px-4 py-3 text-[13px] text-muted-foreground">None. Every checked close note is good enough.</p>}
      <ul role="list">
        {items?.map((t) => (
          <li key={t.ticket_id} className="flex flex-col gap-1.5 border-b border-border px-4 py-3 text-[13px] last:border-b-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <Link href={`/tickets/${encodeURIComponent(t.ticket_id)}`} className="font-mono font-semibold text-primary underline-offset-4 hover:underline">
                {t.ticket_id}
              </Link>
              <span className="min-w-0 break-words">{t.summary}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {[t.application, t.score === null ? "Stopped by the rules" : `Score ${t.score} of 6`].filter(Boolean).join(" · ")}
              </span>
            </div>
            <p className="break-words">{t.reason}</p>
            {t.questions.length > 0 && (
              <ul className="flex list-disc flex-col gap-0.5 break-words pl-5 text-xs text-muted-foreground">
                {t.questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            )}
            {[
              ["Close notes as written", t.notes],
              ["Draft close notes", t.draft_notes],
            ].map(
              ([title, text]) =>
                text && (
                  <details key={title}>
                    <summary className="cursor-pointer text-xs font-semibold text-primary">{title}</summary>
                    <p className="mt-1 whitespace-pre-wrap break-words rounded-lg border border-border bg-muted px-3 py-2">{text}</p>
                  </details>
                ),
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function ClosureAgentPage() {
  return (
    <AppShell>
      <PageHeader
        title="Closure Quality"
        context="Checks the close notes of resolved tickets: what caused it, what fixed it and how the fix was confirmed."
      />
      <AgentRunPanel agent="closure" />
      <Queue />
    </AppShell>
  );
}
