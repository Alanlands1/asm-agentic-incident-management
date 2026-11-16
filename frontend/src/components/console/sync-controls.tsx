"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SyncRun } from "@/components/console/sync-parts";
import { usePerson } from "@/lib/view-as";
import { adminService } from "@/services/admin-service";

/** How often a sync runs by itself. `minutes` is undefined while the connection is still loading. */
export function SyncInterval({
  settingKey,
  minutes,
  onSaved,
  children,
}: {
  settingKey: "JIRA_SYNC_MINUTES" | "CONFLUENCE_SYNC_MINUTES";
  minutes: number | undefined;
  onSaved: (minutes: number) => void;
  /** What an automatic run does, and any note for this page. */
  children?: React.ReactNode;
}) {
  const person = usePerson();
  const id = useId();
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const value = draft ?? (minutes === undefined ? "" : String(minutes));
  const next = Number(value);
  const valid = value.trim() !== "" && Number.isInteger(next) && next >= 0;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adminService.putSetting(settingKey, next, person);
      onSaved(next);
      setDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the interval");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3 text-xs text-muted-foreground">
      <label htmlFor={id}>Runs by itself every</label>
      <Input
        id={id}
        type="number"
        min={0}
        step={1}
        inputMode="numeric"
        value={value}
        placeholder="…"
        disabled={minutes === undefined || busy}
        onChange={(e) => setDraft(e.target.value)}
        className="w-20"
      />
      <span>minutes. 0 turns it off.</span>
      {draft !== null && next !== minutes && (
        <Button type="submit" size="sm" disabled={!valid || busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
      )}
      {children && <span className="basis-full">{children}</span>}
      {error && (
        <span role="alert" className="basis-full text-destructive">
          {error}
        </span>
      )}
    </form>
  );
}

/** Sync runs, newest first. Scheduled runs that found nothing are folded away so the real ones are easy to find. */
export function SyncHistory<T extends SyncRun>({
  runs,
  empty,
  changed,
  children,
}: {
  runs: T[] | null;
  empty: string;
  /** How many things a run changed; scheduled runs with 0 are folded. */
  changed: (run: T) => number;
  children: (run: T) => React.ReactNode;
}) {
  const [all, setAll] = useState(false);
  if (!runs) return <p className="px-4 py-6 text-muted-foreground">Loading sync history…</p>;
  if (runs.length === 0) return <p className="px-4 py-6 text-muted-foreground">{empty}</p>;
  const isQuiet = (r: T) => r.trigger === "schedule" && !r.error && changed(r) === 0;
  const quiet = runs.filter(isQuiet).length;
  const shown = all ? runs : runs.filter((r) => !isQuiet(r));
  return (
    <>
      <ul role="list">{shown.map(children)}</ul>
      {quiet > 0 && (
        <p className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2.5 text-xs text-muted-foreground">
          {quiet} scheduled {quiet === 1 ? "run" : "runs"} found nothing new.
          <Button variant="ghost" size="sm" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? "Hide them" : "Show them"}
          </Button>
        </p>
      )}
    </>
  );
}
