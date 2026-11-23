"use client";

import { useId, useState } from "react";
import { Check, LoaderCircle, ThumbsDown, ThumbsUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { usePerson } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { AgentFeedback } from "@/types/pipeline";
import { cn } from "cn";

const UP = 5;
const DOWN = 1;
const FROM_USE = "From use: ";
// Quick reasons after a thumbs down, per agent: one click each, no typing needed.
const REASONS: Record<string, string[]> = {
  data_quality: ["Asked for details that were there", "Missed what was missing", "Not an incident", "Wrong application"],
  triage: ["Too high", "Too low", "Wrong application", "Missed the impact"],
  resolution: ["Wrong runbook", "Steps incomplete", "Didn't apply here", "Outdated"],
  closure_quality: ["Too strict", "Missed a gap", "Draft not usable"],
};

/**
 * Was this result right? One click: thumbs up or down, saved at once. After a thumbs down, quick reasons for that agent;
 * either way an optional suggestion. A rating "from use" (the engineer agreed, said the fix worked...) shows as given.
 */
export function FeedbackThumbs({
  ticketId,
  runId,
  agent,
  references = [],
  given,
  onSent,
}: {
  ticketId: string;
  runId: number;
  agent: string;
  references?: string[];
  given?: AgentFeedback;
  onSent: () => void;
}) {
  const person = usePerson();
  const id = useId();
  const [thumb, setThumb] = useState<number | null>(null); // chosen here, before the server answers
  const [reasons, setReasons] = useState<string[]>([]);
  const [suggestion, setSuggestion] = useState("");
  const [writing, setWriting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false); // the reasons or suggestion were saved
  const [error, setError] = useState<string | null>(null);

  const current = thumb ?? (given ? (given.stars >= 4 ? UP : given.stars <= 2 ? DOWN : 3) : null);
  const fromUse = !thumb && given?.reason.startsWith(FROM_USE);

  const rate = async (stars: number, reason = "") => {
    setBusy(true);
    setError(null);
    try {
      await pipelineService.rate(ticketId, { agent_run_id: runId, stars, reason, reviewer: person });
      onSent();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save it");
      return false;
    } finally {
      setBusy(false);
    }
  };
  const pick = (stars: number) => {
    setThumb(stars);
    setReasons([]);
    setSaved(false);
    void rate(stars);
  };
  const toggle = (r: string) => {
    setSaved(false);
    setReasons((rs) => (rs.includes(r) ? rs.filter((x) => x !== r) : [...rs, r]));
  };
  const saveDetails = async () => {
    const text = [reasons.join("; "), suggestion.trim() && `Suggestion: ${suggestion.trim()}`].filter(Boolean).join(". ");
    if (await rate(current ?? DOWN, text)) setSaved(true);
  };

  const quick = REASONS[agent] ?? [];
  const showDetails = thumb !== null; // just rated here: offer reasons and a suggestion
  return (
    <div className="flex flex-col gap-2 border-t border-border pt-2.5">
      <div role="group" aria-labelledby={`${id}-q`} className="flex flex-wrap items-center gap-2">
        <span id={`${id}-q`} className="text-xs font-semibold">
          Was this right?
        </span>
        <Button
          size="xs"
          variant={current === UP ? "default" : "secondary"}
          aria-pressed={current === UP}
          disabled={busy}
          onClick={() => pick(UP)}
          className={cn(current === UP && "border-p3 bg-p3 text-white hover:bg-p3/90")}
        >
          <ThumbsUp />
          Right
        </Button>
        <Button size="xs" variant={current === DOWN ? "default" : "secondary"} aria-pressed={current === DOWN} disabled={busy} onClick={() => pick(DOWN)}>
          <ThumbsDown />
          Wrong
        </Button>
        {busy && <LoaderCircle className="size-3.5 animate-spin text-muted-foreground" aria-hidden="true" />}
        <span className="text-xs text-muted-foreground">
          {fromUse
            ? `${given!.reason.slice(FROM_USE.length)} · ${given!.reviewer}`
            : given && !thumb
              ? `${given.reviewer}${given.reason ? ` · “${given.reason}”` : ""}`
              : thumb === UP
                ? "Thanks."
                : thumb === DOWN
                  ? agent === "resolution" && references.length
                    ? `Thanks: ${references.join(", ")} will rank lower for tickets like this.`
                    : "Thanks. What was wrong?"
                  : "One click; it helps the agents learn."}
        </span>
      </div>

      {showDetails && (
        <div className="flex flex-col gap-2 animate-in fade-in duration-300">
          {thumb === DOWN && quick.length > 0 && (
            <div role="group" aria-label="What was wrong" className="flex flex-wrap gap-1.5">
              {quick.map((r) => (
                <Button key={r} size="xs" variant={reasons.includes(r) ? "default" : "outline"} aria-pressed={reasons.includes(r)} onClick={() => toggle(r)}>
                  {reasons.includes(r) && <Check />}
                  {r}
                </Button>
              ))}
            </div>
          )}
          {writing ? (
            <>
              <label htmlFor={`${id}-s`} className="sr-only">
                Your suggestion
              </label>
              <Textarea
                id={`${id}-s`}
                rows={2}
                value={suggestion}
                placeholder={thumb === DOWN ? "What would have been right? E.g. the runbook or step to use instead." : "Anything to make it better?"}
                onChange={(e) => {
                  setSuggestion(e.target.value);
                  setSaved(false);
                }}
              />
            </>
          ) : (
            <Button size="xs" variant="link" className="self-start px-0" onClick={() => setWriting(true)}>
              Add a suggestion (optional)
            </Button>
          )}
          {(reasons.length > 0 || suggestion.trim()) && (
            <div className="flex items-center gap-2">
              <Button size="xs" disabled={busy || saved} onClick={saveDetails}>
                {saved ? <Check /> : null}
                {saved ? "Saved" : "Save"}
              </Button>
              <span className="text-xs text-muted-foreground">Recorded as {person}.</span>
            </div>
          )}
        </div>
      )}

      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
