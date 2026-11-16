"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { SectionHead } from "@/components/console/sync-parts";
import { REVIEW_EVENT } from "@/components/console/review-actions";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api-client";
import { pipelineService } from "@/services/pipeline-service";
import { AgentCheckResult, AgentRunResult, AgentSlug } from "@/types/pipeline";
import { Play } from "lucide-react";

const WAITING: Record<AgentSlug, string> = {
  "data-quality": "new tickets that have not been checked yet",
  triage: "tickets that passed Data Quality",
  resolution: "tickets whose priority a person has approved",
  closure: "resolved tickets whose close notes are new or changed",
};

const AFTER_SYNC: AgentSlug[] = ["data-quality", "triage"]; // the other agents only run when asked

const words = (v: string) => v.replace(/_/g, " ");

function problem(e: unknown, agent: AgentSlug): string {
  if (e instanceof ApiError && e.status === 409) return `${e.message}. This agent only checks ${WAITING[agent]}.`;
  return e instanceof Error ? e.message : "The agent could not be reached";
}

/** Run an agent on everything waiting for it, or on one ticket, and see what it decided. Both write real verdicts. */
export function AgentRunPanel({ agent }: { agent: AgentSlug }) {
  const id = useId();
  const [busy, setBusy] = useState<"run" | "check" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ran, setRan] = useState<AgentRunResult | null>(null);
  const [ticketId, setTicketId] = useState("");
  const [checked, setChecked] = useState<AgentCheckResult | null>(null);

  const start = async (kind: "run" | "check", work: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await work();
      window.dispatchEvent(new Event(REVIEW_EVENT)); // the review queue count may have moved
    } catch (e) {
      setError(problem(e, agent));
    } finally {
      setBusy(null);
    }
  };

  const run = () => start("run", async () => setRan(await pipelineService.run(agent)));
  const check = (e: React.FormEvent) => {
    e.preventDefault();
    setChecked(null);
    void start("check", async () => setChecked(await pipelineService.check(agent, ticketId.trim())));
  };

  const verdicts = ran && Object.entries(ran.by_verdict).map(([v, n]) => `${n} ${words(v)}`).join(", ");
  const single = agent !== "resolution"; // it only has a run endpoint
  const reason = checked && typeof checked.output.reason === "string" ? checked.output.reason : null;

  return (
    <Card className="gap-0 py-0">
      <SectionHead title="Run it">
        <Button onClick={run} disabled={busy !== null}>
          <Play />
          {busy === "run" ? "Running…" : "Run now"}
        </Button>
      </SectionHead>
      <p className="border-b border-border px-4 py-3 text-xs text-muted-foreground" aria-live="polite">
        {ran
          ? ran.evaluated === 0
            ? `Nothing was waiting. ${ran.skipped} already checked and unchanged.`
            : `Checked ${ran.evaluated}: ${verdicts}.${ran.needs_review ? ` ${ran.needs_review} sent to the review queue.` : ""}${
                ran.model_errors ? ` The model failed on ${ran.model_errors}.` : ""
              }`
          : `Run now checks ${WAITING[agent]}.${AFTER_SYNC.includes(agent) ? " It also runs by itself after each sync." : ""}`}
      </p>
      {single && (
        <form onSubmit={check} className="flex flex-wrap items-center gap-2 px-4 py-3">
          <label htmlFor={id} className="text-[13px]">
            Try one ticket
          </label>
          <Input
            id={id}
            value={ticketId}
            onChange={(e) => setTicketId(e.target.value)}
            placeholder="AMS-36"
            className="w-40 font-mono"
            autoComplete="off"
          />
          <Button type="submit" variant="secondary" disabled={busy !== null || !ticketId.trim()}>
            {busy === "check" ? "Checking…" : "Check"}
          </Button>
        </form>
      )}
      {error && (
        <Alert variant="destructive" className="mx-4 mb-4 w-auto">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {checked && (
        <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-4 gap-y-2 border-t border-border px-4 py-3 text-[13px]">
          <dt className="text-muted-foreground">Ticket</dt>
          <dd>
            <Link href={`/tickets/${encodeURIComponent(checked.ticket_id)}`} className="font-mono font-semibold text-primary underline-offset-4 hover:underline">
              {checked.ticket_id}
            </Link>
          </dd>
          <dt className="text-muted-foreground">Verdict</dt>
          <dd className="font-semibold">{words(checked.verdict)}</dd>
          <dt className="text-muted-foreground">Decided by</dt>
          <dd>{checked.stage === "rules" ? "The rules" : words(checked.stage)}</dd>
          {reason && (
            <>
              <dt className="text-muted-foreground">Why</dt>
              <dd>{reason}</dd>
            </>
          )}
          {checked.pipeline_status && (
            <>
              <dt className="text-muted-foreground">Now</dt>
              <dd>{words(checked.pipeline_status)}</dd>
            </>
          )}
        </dl>
      )}
    </Card>
  );
}
