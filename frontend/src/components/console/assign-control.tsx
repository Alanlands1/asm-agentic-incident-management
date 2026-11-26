"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { NO_ENGINEER } from "@/components/console/persona-parts";
import { usePerson } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { cn } from "cn";

export const SELECT =
  "h-8 max-w-44 rounded-lg border border-input bg-background px-2 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-60";

// One read of the engineers for every control on the page.
type Roster = Awaited<ReturnType<typeof pipelineService.roster>>;
let asked: Promise<Roster> | null = null;

/** Everyone a ticket can go to, the team marked. */
function usePeople() {
  const [people, setPeople] = useState<Roster>([]);
  useEffect(() => {
    (asked ??= pipelineService.roster()).then(setPeople, () => {
      asked = null; // read again next time
    });
  }, []);
  return people;
}

/**
 * The lead picks the ticket's engineer; `suggested` adds a button that assigns that engineer in one press.
 * A Jira issue is assigned in Jira too, so an error from there is shown here.
 */
export function AssignControl({
  ticketId,
  assignee,
  suggested,
  onDone,
  className,
}: {
  ticketId: string;
  assignee: string | null;
  suggested?: string;
  onDone: () => unknown;
  className?: string;
}) {
  const people = usePeople();
  const by = usePerson();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const team = people.filter((p) => p.member).map((p) => p.name);
  const others = people.filter((p) => !p.member).map((p) => p.name);
  const unknown = assignee && !people.some((p) => p.name === assignee) ? [assignee] : []; // the list has not loaded, or they left

  const assign = async (name: string) => {
    setBusy(true);
    setError(null);
    try {
      await pipelineService.assign(ticketId, name || null, by);
      await onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't assign the ticket. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className={cn("inline-flex flex-col gap-1", className)}>
      {/* With a suggestion the button sits above the list, so the ticket's text keeps its width in a half-width card. */}
      <span className={suggested && !assignee ? "inline-flex flex-col items-stretch gap-1.5" : "inline-flex items-center"}>
        {suggested && !assignee && (
          <Button size="sm" disabled={busy} onClick={() => assign(suggested)}>
            {busy ? "Assigning…" : `Assign to ${suggested}`}
          </Button>
        )}
        <select aria-label={`Engineer for ${ticketId}`} value={assignee ?? ""} disabled={busy} onChange={(e) => assign(e.target.value)} className={SELECT}>
          <option value="">{NO_ENGINEER}</option>
          {[...unknown, ...team].map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
          {others.length > 0 && (
            <optgroup label="Not on the team">
              {others.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </span>
      {error && (
        <span role="alert" className="max-w-44 text-xs text-critical">
          {error}
        </span>
      )}
    </span>
  );
}
