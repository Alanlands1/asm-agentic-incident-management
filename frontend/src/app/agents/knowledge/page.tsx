"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { SectionHead } from "@/components/console/sync-parts";
import { DraftCard } from "@/components/knowledge/draft-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePerson } from "@/lib/view-as";
import { knowledgeService } from "@/services/knowledge-service";
import { AppCoverage, DraftStatus, KBDraft, KnowledgeRunResult, ProblemCandidate } from "@/types/knowledge";
import { Play } from "lucide-react";

type View = "drafts" | "problems" | "coverage";

const message = (e: unknown, what: string) => (e instanceof Error ? e.message : `${what} could not be loaded`);
const counts = (byKey: Record<string, number>) => Object.entries(byKey).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ");
const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

/** A list that loads itself and reloads after a decision or a run. */
function useList<T>(load: () => Promise<T[]>, what: string, version: number) {
  const [items, setItems] = useState<T[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    load()
      .then((rows) => {
        setItems(rows);
        setError(null);
      })
      .catch((e: unknown) => setError(message(e, what)));
  }, [load, what]);
  useEffect(reload, [reload, version]);
  return { items, error, reload };
}

function Problem({ error }: { error: string | null }) {
  return (
    error && (
      <Alert variant="destructive" className="m-4 w-auto">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    )
  );
}

function Drafts({ version }: { version: number }) {
  const [status, setStatus] = useState<DraftStatus>("draft");
  const load = useCallback(() => knowledgeService.drafts(status), [status]);
  const { items, error, reload } = useList<KBDraft>(load, "The drafts", version);
  return (
    <Card className="gap-0 py-0">
      <SectionHead title={`Drafted articles${items ? ` (${items.length})` : ""}`}>
        <Tabs value={status} onValueChange={(v) => setStatus(v as DraftStatus)}>
          <TabsList variant="pill" aria-label="Which drafts">
            <TabsTrigger value="draft">Waiting</TabsTrigger>
            <TabsTrigger value="approved">Approved</TabsTrigger>
            <TabsTrigger value="rejected">Rejected</TabsTrigger>
            <TabsIndicator />
          </TabsList>
        </Tabs>
      </SectionHead>
      <Problem error={error} />
      {items?.length === 0 && (
        <p className="px-4 py-3 text-[13px] text-muted-foreground">
          {status === "draft" ? "Nothing waiting. A draft appears when a fixed issue has no article yet." : `No ${status} drafts.`}
        </p>
      )}
      <ul role="list">
        {items?.map((d) => (
          <DraftCard key={d.id} draft={d} onDone={reload} />
        ))}
      </ul>
    </Card>
  );
}

function RepeatIssues({ version }: { version: number }) {
  const person = usePerson();
  const { items, error, reload } = useList<ProblemCandidate>(knowledgeService.problems, "The repeat issues", version);
  const [failed, setFailed] = useState<string | null>(null);
  const decide = (id: number, action: "accepted" | "dismissed") =>
    knowledgeService
      .decide(id, action, person)
      .then(reload)
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't save the decision"));
  return (
    <Card className="gap-0 py-0">
      <SectionHead title={`Repeat issues${items ? ` (${items.length})` : ""}`} />
      <Problem error={error ?? failed} />
      {items?.length === 0 && <p className="px-4 py-3 text-[13px] text-muted-foreground">None. No issue keeps coming back.</p>}
      <ul role="list">
        {items?.map((p) => (
          <li key={p.id} className="flex flex-col gap-1.5 border-b border-border px-4 py-3 text-[13px] last:border-b-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-semibold">
                Fixed {p.cases} times between {day(p.first_closed)} and {day(p.last_closed)}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {[p.application, p.issue_key.replace("article:", "").replace("draft:", "Draft #")].filter(Boolean).join(" · ")}
              </span>
            </div>
            <div className="flex flex-wrap gap-x-2">
              {p.ticket_ids.map((t) => (
                <Link key={t} href={`/tickets/${encodeURIComponent(t)}`} className="font-mono text-primary underline-offset-4 hover:underline">
                  {t}
                </Link>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => decide(p.id, "accepted")}>
                Open a problem record
              </Button>
              <Button size="sm" variant="ghost" onClick={() => decide(p.id, "dismissed")}>
                Dismiss
              </Button>
              <span className="text-xs text-muted-foreground">Nothing is created in ServiceNow or Jira; the decision is recorded.</span>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Coverage({ version }: { version: number }) {
  const { items, error } = useList<AppCoverage>(knowledgeService.coverage, "The coverage", version);
  return (
    <Card className="gap-0 py-0">
      <SectionHead title="Coverage per application" />
      <Problem error={error} />
      {items?.length === 0 && <p className="px-4 py-3 text-[13px] text-muted-foreground">No saved cases yet.</p>}
      {items && items.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Application</TableHead>
              <TableHead className="text-right">Cases</TableHead>
              <TableHead className="text-right">Covered</TableHead>
              <TableHead className="text-right">No article</TableHead>
              <TableHead className="text-right">Not for the KB</TableHead>
              <TableHead className="text-right">Drafts waiting</TableHead>
              <TableHead>Articles never used</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((a) => (
              <TableRow key={a.application}>
                <TableCell className="font-medium">{a.application}</TableCell>
                <TableCell className="text-right tabular-nums">{a.cases}</TableCell>
                <TableCell className="text-right tabular-nums">{Math.round(a.covered_share * 100)}%</TableCell>
                <TableCell className="text-right tabular-nums">{a.gap - a.outside_kb}</TableCell>
                <TableCell className="text-right tabular-nums">{a.outside_kb}</TableCell>
                <TableCell className="text-right tabular-nums">{a.drafts_waiting}</TableCell>
                <TableCell className="whitespace-normal font-mono text-xs">
                  {a.unused_articles.length ? a.unused_articles.join(", ") : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}

export default function KnowledgeAgentPage() {
  const [view, setView] = useState<View>("drafts");
  const [version, setVersion] = useState(0); // bumped after a run so every list reloads
  const [busy, setBusy] = useState(false);
  const [ran, setRan] = useState<KnowledgeRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setRan(await knowledgeService.run());
      setVersion((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The agent could not be reached");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppShell>
      <PageHeader
        title="Knowledge Builder"
        context="Learns from close notes that passed Closure Quality: matches each fix to an article, drafts one where none exists, and spots issues that keep coming back. It runs after Closure Quality and after each sync."
        actions={
          <Button onClick={run} disabled={busy}>
            <Play />
            {busy ? "Running…" : "Run now"}
          </Button>
        }
      />
      {(ran || error) && (
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {error ??
            (ran!.evaluated === 0
              ? `Nothing new. ${ran!.skipped} cases already saved and unchanged.`
              : `Saved ${ran!.evaluated}: ${counts(ran!.by_status)}.${Object.keys(ran!.drafts).length ? ` Drafts: ${counts(ran!.drafts)}.` : ""}${
                  ran!.model_errors ? ` The model failed on ${ran!.model_errors}.` : ""
                }`)}
        </p>
      )}
      <Tabs value={view} onValueChange={(v) => setView(v as View)}>
        <TabsList aria-label="Knowledge Builder">
          <TabsTrigger value="drafts">Drafts</TabsTrigger>
          <TabsTrigger value="problems">Repeat issues</TabsTrigger>
          <TabsTrigger value="coverage">Coverage</TabsTrigger>
          <TabsIndicator />
        </TabsList>
      </Tabs>
      <div role="tabpanel">
        {view === "drafts" && <Drafts version={version} />}
        {view === "problems" && <RepeatIssues version={version} />}
        {view === "coverage" && <Coverage version={version} />}
      </div>
    </AppShell>
  );
}
