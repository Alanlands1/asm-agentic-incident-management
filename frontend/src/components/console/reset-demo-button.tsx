"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api-client";

type ResetResult = {
  tickets: number;
  jira_issues: number;
  jira_comments_deleted: number;
  jira_moved_back: number;
  jira_priorities_restored: number;
  jira_errors: string[];
  /** When the saved baseline was taken, if the reset restored one; otherwise the open tickets started again. */
  restored_from?: string | null;
  jira_closed?: number;
};

/** The trigger is a red button by default; the sidebar passes its own look and label content. */
export function ResetDemoButton({
  variant = "destructive",
  className,
  children = "Reset demo",
}: {
  variant?: React.ComponentProps<typeof Button>["variant"];
  className?: string;
  children?: React.ReactNode;
} = {}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ResetResult | null>(null);

  const reset = async () => {
    setBusy(true);
    setError(null);
    try {
      setDone(await apiClient<ResetResult>("/demo/reset", { method: "POST" }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "The reset failed. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const close = (next: boolean) => {
    setOpen(next);
    if (!next && done) window.location.reload(); // every panel shows the fresh state
    if (!next) {
      setDone(null);
      setError(null);
    }
  };

  return (
    <>
      <Button variant={variant} className={className} onClick={() => setOpen(true)}>
        {children}
      </Button>
      <Dialog open={open} onOpenChange={close}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{done ? "Reset complete" : "Reset all open tickets?"}</DialogTitle>
            <DialogDescription>
              {done?.restored_from
                ? `The console and Jira are back to the state saved on ${new Date(done.restored_from).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}, with every clock reading as it did then. In Jira: ${done.jira_issues} issues checked, ${done.jira_comments_deleted} later agent comments deleted, ${done.jira_moved_back} moved back, ${done.jira_priorities_restored} priorities restored, ${done.jira_closed ?? 0} newer issues closed.`
                : done
                ? `${done.tickets} open tickets start again with fresh SLA clocks. In Jira: ${done.jira_issues} issues cleaned, ${done.jira_comments_deleted} agent comments deleted, ${done.jira_moved_back} moved back, ${done.jira_priorities_restored} priorities restored. The agents are running again now.`
                : "Every SLA clock restarts from now, and the agents' results, reviews and ratings on open tickets are cleared. On the open Jira issues the agents' comments and ams-* labels are deleted and each issue goes back to the status it was created in. This can't be undone in Jira. Closed tickets and people's own comments are kept. When a saved baseline is set up, the console and Jira go back to that saved state instead."}
            </DialogDescription>
          </DialogHeader>
          {done && done.jira_errors.length > 0 && (
            <p className="text-sm text-critical">Not cleaned in Jira: {done.jira_errors.join("; ")}</p>
          )}
          {error && <p className="text-sm text-critical">{error}</p>}
          <DialogFooter>
            {done ? (
              <Button onClick={() => close(false)}>Close</Button>
            ) : (
              <>
                <Button variant="secondary" onClick={() => close(false)} disabled={busy}>
                  Cancel
                </Button>
                <Button variant="destructive" onClick={reset} disabled={busy}>
                  {busy ? "Resetting…" : "Reset all"}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
