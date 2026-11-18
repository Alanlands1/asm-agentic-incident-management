"use client";

import { useId, useState } from "react";
import { Star } from "lucide-react";
import { cn } from "cn";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { usePerson } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { AgentFeedback } from "@/types/pipeline";

/** Rate one agent result: one to five stars and why. `given` is the rating already on it, which can be changed. */
export function FeedbackStars({
  ticketId,
  runId,
  given,
  onSent,
}: {
  ticketId: string;
  runId: number;
  given?: AgentFeedback;
  onSent: () => void;
}) {
  const person = usePerson();
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [stars, setStars] = useState(given?.stars ?? 0);
  const [reason, setReason] = useState(given?.reason ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (given && !editing)
    return (
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span className="break-words">
          <Star className="mr-1 inline size-3 fill-current align-[-1px] text-primary" aria-hidden="true" />
          <span className="font-semibold text-foreground">Rated {given.stars} of 5</span> by {given.reviewer} · “{given.reason}”
        </span>
        <Button size="xs" variant="secondary" onClick={() => setEditing(true)}>
          Change
        </Button>
      </p>
    );

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await pipelineService.rate(ticketId, { agent_run_id: runId, stars, reason: reason.trim(), reviewer: person });
      setEditing(false);
      onSent();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the rating");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2 rounded-[14px] border border-border bg-muted p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span id={`${id}-q`} className="text-xs font-semibold">
          Was this result right?
        </span>
        <div role="group" aria-labelledby={`${id}-q`} className="flex gap-0.5">
          {[1, 2, 3, 4, 5].map((n) => (
            <Button
              key={n}
              variant="ghost"
              size="icon-xs"
              aria-label={`${n} ${n === 1 ? "star" : "stars"}`}
              aria-pressed={stars === n}
              onClick={() => setStars(n)}
            >
              <Star className={cn("size-4", n <= stars ? "fill-current text-primary" : "text-muted-foreground")} />
            </Button>
          ))}
        </div>
        {stars > 0 && <span className="text-xs text-muted-foreground">{stars} of 5</span>}
      </div>
      <label htmlFor={`${id}-r`} className="text-xs font-medium">
        Why this many stars
      </label>
      <Textarea id={`${id}-r`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={send} disabled={busy || stars === 0 || !reason.trim()}>
          {busy ? "Sending…" : "Send rating"}
        </Button>
        {given && (
          <Button size="sm" variant="secondary" onClick={() => setEditing(false)} disabled={busy}>
            Cancel
          </Button>
        )}
        <span className="text-xs text-muted-foreground">Recorded as {person}. A rating of a Resolution result moves its runbooks up or down for tickets of the same kind.</span>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertDescription className="break-words">{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
