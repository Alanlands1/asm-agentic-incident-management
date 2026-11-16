"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { hintFor, humanize } from "@/components/console/document-hints";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { jsonDiff } from "@/lib/json-diff";
import { usePerson } from "@/lib/view-as";
import { adminService } from "@/services/admin-service";
import { AdminChange, Json, SettingValue } from "@/types/admin";
import { ChevronDown, ChevronRight } from "lucide-react";

type Filter = "all" | "setting" | "document";

const LABELS: Record<string, string> = {
  // Settings
  LOG_LEVEL: "Log level",
  PII_MASKING_ENABLED: "Masking of personal details",
  LLM_ENABLED: "Model calls",
  LLM_PROVIDER: "Model provider",
  LLM_MODEL: "Shared model",
  LLM_EFFORT: "Shared effort",
  DQ_LLM_MODEL: "Data Quality model",
  DQ_LLM_EFFORT: "Data Quality effort",
  TRIAGE_LLM_MODEL: "Triage model",
  TRIAGE_LLM_EFFORT: "Triage effort",
  LLM_REFUSAL_FALLBACK: "Fallback when the model refuses",
  LLM_TIMEOUT_S: "Model timeout (seconds)",
  LLM_TRANSPORT_RETRIES: "Model retries",
  LLM_VALIDATION_ATTEMPTS: "Attempts at a valid answer",
  AWS_REGION: "AWS region",
  DQ_OUTAGE_BREAKER: "Data Quality: stop after failures",
  TRIAGE_OUTAGE_BREAKER: "Triage: stop after failures",
  JIRA_SYNC_MINUTES: "Jira sync interval (minutes)",
  CONFLUENCE_SYNC_MINUTES: "Confluence sync interval (minutes)",
  // Reference files
  data_quality_rules: "Data Quality rules",
  data_quality_prompts: "Prompts",
  triage_rules: "Triage rules",
  triage_jobs: "Batch jobs",
  apps: "Applications",
  pii: "Privacy terms",
  sla: "SLA times",
  storms: "Storm detection",
};

const nameOf = (c: AdminChange) => LABELS[c.key] ?? humanize(c.key.toLowerCase());

const show = (v: unknown) =>
  v === undefined ? "(not there)" : v === null ? "(empty)" : typeof v === "string" ? v : JSON.stringify(v, null, 2);

/** "Application rules › SAP › Tier": hint labels where there are any, list positions as #1, #2. */
function crumbs(doc: string, path: string[]): string {
  return path
    .map((seg, i) => {
      if (/^\d+$/.test(seg)) return `#${Number(seg) + 1}`;
      const label = hintFor(doc, path.slice(0, i + 1).map((s) => (/^\d+$/.test(s) ? "*" : s))).label;
      return label ?? humanize(seg);
    })
    .join(" › ");
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-accent px-3 py-2 font-mono text-xs">{value}</pre>
    </div>
  );
}

const MOST = 12;

function Details({ change: c }: { change: AdminChange }) {
  if (c.kind === "setting") {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        <Value label="Before" value={show(c.old_value)} />
        <Value label="After" value={c.new_value === null ? "(the default from backend/.env)" : show(c.new_value)} />
      </div>
    );
  }
  if (c.new_value === null) return <p className="text-[13px]">The admin version was removed. The file in the repo is in use again.</p>;
  const changes = jsonDiff(c.old_value, c.new_value);
  if (changes.length === 0) return <p className="text-[13px]">Saved with no differences.</p>;
  return (
    <ul role="list" className="flex flex-col gap-3">
      {changes.slice(0, MOST).map((d) => (
        <li key={d.path.join("/")}>
          <p className="text-[13px] font-medium">{crumbs(c.key, d.path) || "Whole file"}</p>
          <div className="mt-1 grid gap-3 md:grid-cols-2">
            <Value label="Before" value={show(d.before)} />
            <Value label="After" value={show(d.after)} />
          </div>
        </li>
      ))}
      {changes.length > MOST && <li className="text-xs text-muted-foreground">And {changes.length - MOST} more fields.</li>}
    </ul>
  );
}

/** Every admin change to a setting or reference file, newest first. Any of them can be put back. */
export default function ChangeHistoryPage() {
  const person = usePerson();
  const [changes, setChanges] = useState<AdminChange[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<AdminChange | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      adminService
        .listChanges(200)
        .then(setChanges)
        .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load the change history")),
    [],
  );
  useEffect(() => {
    void load();
  }, [load]);

  const restore = async () => {
    if (!restoring) return;
    setBusy(true);
    setError(null);
    try {
      const { kind, key, old_value } = restoring;
      // Nothing was set before this change: restoring means removing the admin value.
      if (kind === "setting") await (old_value === null ? adminService.resetSetting(key, person) : adminService.putSetting(key, old_value as SettingValue, person));
      else await (old_value === null ? adminService.resetDocument(key, person) : adminService.putDocument(key, old_value as Json, person));
      setOpen(null);
      await load();
    } catch (e) {
      setError(`${nameOf(restoring)} was not restored: ${e instanceof Error ? e.message : "the backend refused it"}`);
    } finally {
      setBusy(false);
      setRestoring(null);
    }
  };

  const shown = (changes ?? []).filter((c) => filter === "all" || c.kind === filter);

  return (
    <AppShell>
      <PageHeader title="Change history" context="Who changed which setting or reference file, and when. Names come from the demo role until there is sign-in." />
      <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)}>
        <TabsList aria-label="Kind of change">
          {(
            [
              ["all", "All"],
              ["setting", "Settings"],
              ["document", "Files"],
            ] as const
          ).map(([value, label]) => (
            <TabsTrigger key={value} value={value}>
              {label}
            </TabsTrigger>
          ))}
          <TabsIndicator />
        </TabsList>
      </Tabs>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Card className="gap-0 py-0" role="tabpanel">
        {!changes && !error ? (
          <p className="px-4 py-6 text-muted-foreground">Loading…</p>
        ) : shown.length === 0 ? (
          <p className="px-4 py-6 text-muted-foreground">No changes yet.</p>
        ) : (
          <ul role="list">
            {shown.map((c) => {
              const expanded = open === c.id;
              const Icon = expanded ? ChevronDown : ChevronRight;
              return (
                <li key={c.id} className="border-b border-border last:border-b-0">
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => setOpen(expanded ? null : c.id)}
                    className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-[13px] font-medium">
                        {nameOf(c)} {c.new_value === null ? "reset to default" : "changed"}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {c.kind === "setting" ? "Setting" : "File"} · by {c.claimed_by} · {new Date(c.changed_at).toLocaleString()}
                      </span>
                    </span>
                  </button>
                  {expanded && (
                    <div className="flex flex-col gap-3 px-4 pb-3 pl-11">
                      <Details change={c} />
                      <div>
                        <Button variant="secondary" onClick={() => setRestoring(c)}>
                          Restore the version before this change
                        </Button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Dialog open={!!restoring} onOpenChange={(o) => !o && !busy && setRestoring(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restore {restoring && nameOf(restoring)}?</DialogTitle>
            <DialogDescription>
              It goes back to what it was before this change, from {restoring && new Date(restoring.changed_at).toLocaleString()}. Anything changed since then
              is replaced, and the restore is added to this history.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="secondary" />}>Cancel</DialogClose>
            <Button onClick={restore} disabled={busy}>
              {busy ? "Restoring…" : "Restore"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
