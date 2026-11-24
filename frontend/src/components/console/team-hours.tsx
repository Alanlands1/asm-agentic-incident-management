"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/console/app-shell";
import { SELECT } from "@/components/console/assign-control";
import { stateWords } from "@/components/console/lead-desk";
import { ListRow } from "@/components/console/list-row";
import { PageHeader } from "@/components/console/page-header";
import { SectionHead } from "@/components/console/sync-parts";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePerson } from "@/lib/view-as";
import { adminService } from "@/services/admin-service";
import { pipelineService } from "@/services/pipeline-service";
import { Json } from "@/types/admin";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
type Hours = { days: string[]; start: string; end: string };
type Leave = { name: string; from: string; to: string };
/** data/registry/team.yaml, as the admin API returns it. */
type Team = {
  utc_offset: string;
  default: Hours;
  engineers: Record<string, Partial<Hours>> | null;
  leave: Leave[] | null;
  members?: string[] | null; // put on the team by the lead
  not_members?: string[] | null; // taken off it
  max_open?: number; // open tickets at which an engineer is suggested no more
};
type Roster = Awaited<ReturnType<typeof pipelineService.roster>>;
type Working = Awaited<ReturnType<typeof pipelineService.availability>>;

const day = (iso: string) => new Date(`${iso}T00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

/** One row of working hours: the days as toggles, then when the day starts and ends. */
function HoursRow({
  label,
  hours,
  now,
  onChange,
  onReset,
  onRemove,
}: {
  label: string;
  hours: Hours;
  now?: string;
  onChange: (h: Hours) => void;
  onReset?: () => void;
  onRemove?: () => void;
}) {
  return (
    <TableRow>
      <TableCell className="pl-4 font-medium">{label}</TableCell>
      <TableCell>
        <div role="group" aria-label={`Working days for ${label}`} className="flex flex-wrap gap-1">
          {DAYS.map((d) => {
            const on = hours.days.includes(d);
            return (
              <Button
                key={d}
                size="xs"
                variant={on ? "default" : "secondary"}
                aria-pressed={on}
                className="capitalize"
                onClick={() => onChange({ ...hours, days: on ? hours.days.filter((x) => x !== d) : DAYS.filter((x) => x === d || hours.days.includes(x)) })}
              >
                {d}
              </Button>
            );
          })}
        </div>
      </TableCell>
      <TableCell>
        <Input type="time" aria-label={`Start for ${label}`} value={hours.start} onChange={(e) => onChange({ ...hours, start: e.target.value })} className="w-32" />
      </TableCell>
      <TableCell>
        <Input type="time" aria-label={`End for ${label}`} value={hours.end} onChange={(e) => onChange({ ...hours, end: e.target.value })} className="w-32" />
      </TableCell>
      <TableCell className="text-muted-foreground">{now ?? ""}</TableCell>
      <TableCell className="pr-4 text-right">
        {onReset && (
          <Button size="sm" variant="ghost" onClick={onReset}>
            Use team hours
          </Button>
        )}
        {onRemove && (
          <Button size="sm" variant="ghost" onClick={onRemove}>
            Take off the team
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

/**
 * The lead's page for who works when: the team's hours, an engineer's own hours, and days of leave. Saved as the
 * reference document "team"; the suggested engineer and the workload table follow it at once.
 */
export function TeamHours() {
  const by = usePerson();
  const [team, setTeam] = useState<Team | null>(null);
  const [saved, setSaved] = useState<string | null>(null); // the document as last loaded or saved
  const [people, setPeople] = useState<Roster>([]);
  const [working, setWorking] = useState<Working>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [leave, setLeave] = useState<Leave>({ name: "", from: "", to: "" });

  const load = useCallback(() => {
    adminService.getDocument("team").then(
      (d) => {
        setTeam(d.document as unknown as Team);
        setSaved(JSON.stringify(d.document));
      },
      (e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load the team's hours. Try again.")
    );
    pipelineService.availability().then(setWorking, () => setWorking({}));
  }, []);
  useEffect(() => {
    load();
    pipelineService.roster().then(setPeople, () => setPeople([]));
  }, [load]);

  const own = team?.engineers ?? {};
  // On the team: put on by the lead; else someone who has held a ticket, unless Jira no longer lets them be assigned.
  const put = team?.members ?? [];
  const taken = team?.not_members ?? [];
  const onTeam = (p: Roster[number]) => !taken.includes(p.name) && (put.includes(p.name) || (p.held && p.in_jira !== false));
  const names = people.filter(onTeam).map((p) => p.name);
  const others = people.filter((p) => !onTeam(p));
  const setMember = (name: string, on: boolean) =>
    team &&
    setTeam({
      ...team,
      members: on ? [...put.filter((n) => n !== name), name] : put.filter((n) => n !== name),
      not_members: on ? taken.filter((n) => n !== name) : [...taken.filter((n) => n !== name), name],
    });
  const days = team?.leave ?? [];
  const dirty = team !== null && JSON.stringify(team) !== saved;
  const canAdd = leave.name && leave.from && leave.to && leave.from <= leave.to;

  const setOwn = (name: string, hours?: Hours) => {
    if (!team) return;
    const engineers = { ...own };
    if (hours) engineers[name] = hours;
    else delete engineers[name];
    setTeam({ ...team, engineers });
  };
  const save = async () => {
    if (!team) return;
    setSaving(true);
    setError(null);
    try {
      await adminService.putDocument("team", team as unknown as Json, by);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save. Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell>
      <PageHeader
        title="Team hours and leave"
        context="Who can be given a ticket now. Nobody on leave is suggested, and someone off shift only when nobody is on shift."
        actions={
          <>
            <Button variant="secondary" nativeButton={false} render={<Link href="/lead" />}>
              Lead desk
            </Button>
            <Button onClick={save} disabled={!dirty || saving}>
              {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
            </Button>
          </>
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="gap-0 py-0">
        <SectionHead title="Working hours">
          {team && (
            <label className="flex items-center gap-2 text-xs text-muted-foreground" title="Nobody holding this many open tickets is suggested another, unless it is a P1 or P2">
              Most open tickets each
              <Input
                type="number"
                min={1}
                aria-label="Most open tickets an engineer holds before no more are suggested"
                value={team.max_open ?? 8}
                onChange={(e) => setTeam({ ...team, max_open: Math.max(1, Number(e.target.value) || 1) })}
                className="w-16"
              />
            </label>
          )}
          {team && (
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Team&rsquo;s time is UTC
              <Input aria-label="The team's time, as a distance from UTC" value={team.utc_offset} onChange={(e) => setTeam({ ...team, utc_offset: e.target.value })} className="w-20" />
            </label>
          )}
        </SectionHead>
        {!team ? (
          <div className="flex flex-col gap-3 px-4 py-3">{error ? null : Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-6" />)}</div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Engineer</TableHead>
                <TableHead>Days</TableHead>
                <TableHead>Start</TableHead>
                <TableHead>End</TableHead>
                <TableHead>Now</TableHead>
                <TableHead className="pr-4" />
              </TableRow>
            </TableHeader>
            <TableBody>
              <HoursRow label="Team hours" hours={team.default} onChange={(h) => setTeam({ ...team, default: h })} />
              {names.map((name) => (
                <HoursRow
                  key={name}
                  label={name}
                  hours={{ ...team.default, ...own[name] }}
                  now={working[name] && stateWords(working[name])}
                  onChange={(h) => setOwn(name, h)}
                  onReset={own[name] ? () => setOwn(name) : undefined}
                  onRemove={() => setMember(name, false)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {team && others.length > 0 && (
        <Card className="gap-0 py-0">
          <SectionHead title={`Not on the team · ${others.length}`}>
            <span className="hidden text-xs text-muted-foreground sm:inline">They can still be given a ticket by hand, but are never suggested</span>
          </SectionHead>
          <ul role="list">
            {others.map((p) => (
              <ListRow
                key={p.name}
                title={p.name}
                meta={taken.includes(p.name) ? "Taken off the team" : p.in_jira === false ? "Can no longer be assigned in Jira" : "Can be assigned in Jira, has not held a ticket here"}
                actions={
                  <Button size="sm" variant="secondary" onClick={() => setMember(p.name, true)}>
                    Add to the team
                  </Button>
                }
              />
            ))}
          </ul>
        </Card>
      )}

      {team && (
        <Card className="gap-0 py-0">
          <SectionHead title={`Leave · ${days.length}`} />
          {days.length === 0 ? (
            <p className="px-4 py-3 text-[13px] text-muted-foreground">Nobody has leave booked.</p>
          ) : (
            <ul role="list">
              {days.map((l, i) => (
                <ListRow
                  key={`${l.name} ${l.from} ${l.to} ${i}`}
                  title={l.name}
                  meta={l.from === l.to ? day(l.from) : `${day(l.from)} to ${day(l.to)}`}
                  actions={
                    <Button size="sm" variant="secondary" onClick={() => setTeam({ ...team, leave: days.filter((_, j) => j !== i) })}>
                      Remove
                    </Button>
                  }
                />
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-end gap-3 border-t border-border px-4 py-3">
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Engineer
              <select value={leave.name} onChange={(e) => setLeave({ ...leave, name: e.target.value })} className={SELECT}>
                <option value="">Choose…</option>
                {names.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              First day
              <Input type="date" value={leave.from} onChange={(e) => setLeave({ ...leave, from: e.target.value, to: leave.to || e.target.value })} className="w-40" />
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              Last day
              <Input type="date" value={leave.to} min={leave.from} onChange={(e) => setLeave({ ...leave, to: e.target.value })} className="w-40" />
            </label>
            <Button
              variant="secondary"
              disabled={!canAdd}
              onClick={() => {
                setTeam({ ...team, leave: [...days, leave] });
                setLeave({ name: "", from: "", to: "" });
              }}
            >
              Add leave
            </Button>
          </div>
        </Card>
      )}
    </AppShell>
  );
}
