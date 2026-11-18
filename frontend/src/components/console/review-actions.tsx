"use client";

import { useId, useState } from "react";
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
import { usePerson } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { REASON_CODES, ReviewInput } from "@/types/pipeline";

/** Fired after every review so the sidebar count and open lists refresh. */
export const REVIEW_EVENT = "ams-review";

const SELECT =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** Agree with the recommended priority, or change it with a reason. Only for tickets waiting for an engineer. */
export function ReviewActions({ ticketId, recommended, onDone }: { ticketId: string; recommended: number; onDone: () => void }) {
  const person = usePerson();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [priority, setPriority] = useState(recommended === 1 ? 2 : recommended - 1);
  const [reason, setReason] = useState<NonNullable<ReviewInput["reason_code"]> | "">(""); // no default: a preset reason skews the rule stats
  const [note, setNote] = useState("");

  const send = async (body: Omit<ReviewInput, "reviewer">) => {
    setBusy(true);
    setError(null);
    try {
      await pipelineService.review(ticketId, { ...body, reviewer: person });
      setOpen(false);
      window.dispatchEvent(new Event(REVIEW_EVENT));
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the decision");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button size="sm" onClick={() => send({ action: "accepted" })} disabled={busy}>
        Agree with P{recommended}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)} disabled={busy}>
          Change
        </Button>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Change the priority of {ticketId}</DialogTitle>
            <DialogDescription>
              The agent recommends P{recommended}. Your priority and reason are recorded as {person}. When writing to Jira is switched on, the priority of a Jira issue is set to match.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 text-[13px]">
            <div className="flex flex-col gap-1">
              <label htmlFor={`${id}-p`} className="font-medium">
                Priority
              </label>
              <select id={`${id}-p`} className={SELECT} value={priority} onChange={(e) => setPriority(Number(e.target.value))}>
                {[1, 2, 3, 4, 5]
                  .filter((p) => p !== recommended)
                  .map((p) => (
                    <option key={p} value={p}>
                      P{p}
                    </option>
                  ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`${id}-r`} className="font-medium">
                Why
              </label>
              <select id={`${id}-r`} className={SELECT} value={reason} onChange={(e) => setReason(e.target.value as typeof reason)}>
                <option value="">Pick a reason (optional)</option>
                {REASON_CODES.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`${id}-n`} className="font-medium">
                Note (optional)
              </label>
              <Textarea id={`${id}-n`} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <DialogClose render={<Button variant="secondary" />}>Cancel</DialogClose>
            <Button onClick={() => send({ action: "edited", priority, reason_code: reason || undefined, note: note.trim() || undefined })} disabled={busy}>
              {busy ? "Saving…" : `Set P${priority}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {error && (
        <Alert variant="destructive" className="sm:max-w-xs">
          <AlertDescription className="break-words">{error}</AlertDescription>
        </Alert>
      )}
    </>
  );
}
