"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/console/app-shell";
import { PageHeader } from "@/components/console/page-header";
import { ListRow } from "@/components/console/list-row";
import { SyncHistory, SyncInterval } from "@/components/console/sync-controls";
import { SectionHead, Status, SyncHistoryRow } from "@/components/console/sync-parts";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { confluenceService } from "@/services/confluence-service";
import { ConfluenceConnection, ConfluencePage, ConfluencePageDetail, ConfluenceSpace, ConfluenceSync } from "@/types/confluence";
import { ExternalLink, FileText, RefreshCw } from "lucide-react";

const message = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);
const offline = (e: unknown): ConfluenceConnection => ({ site: "", connected: false, error: message(e, "Couldn't reach the backend"), sync_minutes: 0 });

/** Admin: Confluence connection, which spaces to copy, sync history and the copied pages. Read-only towards Confluence. */
export default function ConfluenceSettingsPage() {
  const [conn, setConn] = useState<ConfluenceConnection | null>(null);
  const [testing, setTesting] = useState(false);
  const [spaces, setSpaces] = useState<ConfluenceSpace[] | null>(null);
  const [spacesError, setSpacesError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [syncs, setSyncs] = useState<ConfluenceSync[] | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [pages, setPages] = useState<ConfluencePage[] | null>(null);
  const [preview, setPreview] = useState<{ page: ConfluencePage; detail?: ConfluencePageDetail; error?: string } | null>(null);

  const openPreview = (page: ConfluencePage) => {
    setPreview({ page });
    confluenceService
      .getPage(page.id)
      .then((detail) => setPreview((p) => (p?.page.id === page.id ? { page, detail } : p)))
      .catch((e: unknown) => setPreview((p) => (p?.page.id === page.id ? { page, error: message(e, "Couldn't load the page") } : p)));
  };

  const loadCopies = () => {
    confluenceService.getSyncs().then(setSyncs).catch((e: unknown) => setSyncError(message(e, "Couldn't load sync history")));
    confluenceService.getPages().then(setPages).catch((e: unknown) => setSyncError(message(e, "Couldn't load copied pages")));
  };

  useEffect(() => {
    confluenceService.getConnection().then(setConn).catch((e: unknown) => setConn(offline(e)));
    confluenceService.getSpaces().then(setSpaces).catch((e: unknown) => setSpacesError(message(e, "Couldn't load Confluence spaces")));
    confluenceService.getSyncs().then(setSyncs).catch((e: unknown) => setSyncError(message(e, "Couldn't load sync history")));
    confluenceService.getPages().then(setPages).catch((e: unknown) => setSyncError(message(e, "Couldn't load copied pages")));
  }, []);

  const testConnection = async () => {
    setTesting(true);
    try {
      setConn(await confluenceService.getConnection());
    } catch (e) {
      setConn(offline(e));
    } finally {
      setTesting(false);
    }
  };

  const toggle = (key: string, selected: boolean) => {
    setSpaces((ss) => ss && ss.map((s) => (s.key === key ? { ...s, selected } : s)));
    setDirty(true);
    setSaved(false);
  };

  const save = async () => {
    if (!spaces) return;
    setSaving(true);
    setSpacesError(null);
    try {
      await confluenceService.saveSpaces(spaces.filter((s) => s.selected).map(({ key, id, name }) => ({ key, id, name })));
      setDirty(false);
      setSaved(true);
    } catch (e) {
      setSpacesError(message(e, "Couldn't save spaces"));
    } finally {
      setSaving(false);
    }
  };

  const syncNow = async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      const run = await confluenceService.syncNow();
      if (run.error) setSyncError(run.error);
    } catch (e) {
      setSyncError(message(e, "Sync failed"));
    } finally {
      setSyncing(false);
      loadCopies();
    }
  };

  const selectedCount = spaces?.filter((s) => s.selected).length ?? 0;
  const name = (key: string) => spaces?.find((s) => s.key === key)?.name ?? key;

  return (
    <AppShell>
      <PageHeader
        title="Confluence"
        context="Copy knowledge base pages from Confluence for the agents to read. Nothing is written back to Confluence."
        actions={
          <Button variant="secondary" onClick={testConnection} disabled={testing}>
            {testing ? "Testing…" : "Test connection"}
          </Button>
        }
      />

      <Card className="gap-0 py-0">
        <SectionHead title="Connection">
          {conn && <Status ok={conn.connected}>{conn.connected ? "Connected" : "Not connected"}</Status>}
        </SectionHead>
        {!conn ? (
          <p className="px-4 py-6 text-muted-foreground">Testing the connection…</p>
        ) : (
          <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-4 gap-y-2 px-4 py-3 text-[13px]">
            <dt className="text-muted-foreground">Site</dt>
            <dd className="break-all">{conn.site ? `${conn.site}/wiki` : "Not set"}</dd>
            <dt className="text-muted-foreground">Signed in as</dt>
            <dd>{conn.account_name ?? "—"}</dd>
            <dt className="text-muted-foreground">API token</dt>
            <dd>Same as Jira, from backend/.env</dd>
            {conn.error && (
              <>
                <dt className="text-muted-foreground">Problem</dt>
                <dd>{conn.error}</dd>
              </>
            )}
          </dl>
        )}
      </Card>

      <Card className="gap-0 py-0">
        <SectionHead title="Spaces">
          <span className="text-xs text-muted-foreground">
            {saved && !dirty ? "Saved" : dirty ? "Unsaved changes" : `${selectedCount} selected`}
          </span>
        </SectionHead>
        {spacesError && (
          <Alert variant="destructive" className="m-4 w-auto">
            <AlertDescription>{spacesError}</AlertDescription>
          </Alert>
        )}
        {!spaces ? (
          !spacesError && <p className="px-4 py-6 text-muted-foreground">Loading Confluence spaces…</p>
        ) : spaces.length === 0 ? (
          <p className="px-4 py-6 text-muted-foreground">This Confluence site has no shared spaces you can see.</p>
        ) : (
          <ul role="list">
            {spaces.map((s) => (
              <li key={s.key} className="border-b border-border px-4 py-2.5 last:border-b-0">
                <label className="flex items-center gap-3 text-[13px]">
                  <input
                    type="checkbox"
                    checked={s.selected}
                    onChange={(e) => toggle(s.key, e.target.checked)}
                    className="size-4 shrink-0 accent-primary"
                  />
                  <span className="min-w-0">
                    <span className="font-medium">{s.name}</span>
                    <span className="ml-2 text-muted-foreground">{s.key}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {spaces && spaces.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-3">
            <p className="text-xs text-muted-foreground">Personal spaces are not listed.</p>
            <Button onClick={save} disabled={!dirty || saving}>
              {saving ? "Saving…" : "Save spaces"}
            </Button>
          </div>
        )}
      </Card>

      <Card className="gap-0 py-0">
        <SectionHead title="Sync">
          <Button onClick={syncNow} disabled={syncing || dirty || selectedCount === 0 || !conn?.connected}>
            <RefreshCw className={syncing ? "animate-spin motion-reduce:animate-none" : undefined} />
            {syncing ? "Syncing…" : "Sync now"}
          </Button>
        </SectionHead>
        <SyncInterval
          settingKey="CONFLUENCE_SYNC_MINUTES"
          minutes={conn?.sync_minutes}
          onSaved={(sync_minutes) => setConn((c) => c && { ...c, sync_minutes })}
        >
          Pages deleted in Confluence are removed here too.{dirty && " Save your space changes before syncing."}
        </SyncInterval>
        {syncError && (
          <Alert variant="destructive" className="m-4 w-auto">
            <AlertDescription>{syncError}</AlertDescription>
          </Alert>
        )}
        <SyncHistory
          runs={syncs && syncs.slice(0, 10)}
          empty="No syncs yet. Pick your spaces, save, then select Sync now."
          changed={(s) => s.created + s.updated + s.removed}
        >
          {(s) => (
            <SyncHistoryRow
              key={s.id}
              run={s}
              summary={`Copied ${s.pulled} · ${s.created} new · ${s.updated} changed${s.removed ? ` · ${s.removed} removed` : ""}`}
              scope={s.spaces || "No spaces"}
            />
          )}
        </SyncHistory>
      </Card>

      <Card className="gap-0 py-0">
        <SectionHead title="Copied pages">
          <span className="text-xs text-muted-foreground">{pages ? `${pages.length} pages` : "Loading…"}</span>
        </SectionHead>
        {pages && pages.length === 0 ? (
          <p className="px-4 py-6 text-muted-foreground">Nothing copied yet.</p>
        ) : (
          <ul role="list">
            {pages?.map((p) => (
              <ListRow
                key={p.id}
                lead={<FileText className="size-4" aria-hidden="true" />}
                title={p.title}
                meta={`${name(p.space_key)} · version ${p.version} · copied ${new Date(p.synced_at).toLocaleString()}`}
                actions={
                  <>
                    <Button variant="ghost" onClick={() => openPreview(p)}>
                      Preview
                      <span className="sr-only"> {p.title}</span>
                    </Button>
                    {p.url && (
                      <Button variant="ghost" render={<a href={p.url} target="_blank" rel="noopener noreferrer" />} nativeButton={false}>
                        Open
                        <ExternalLink />
                        <span className="sr-only"> {p.title} in Confluence (opens in a new tab)</span>
                      </Button>
                    )}
                  </>
                }
              />
            ))}
          </ul>
        )}
      </Card>

      <Dialog open={!!preview} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{preview?.page.title}</DialogTitle>
            <DialogDescription>
              {preview && `${name(preview.page.space_key)} · version ${preview.page.version}. This is the text the agents read.`}
            </DialogDescription>
          </DialogHeader>
          {preview?.error ? (
            <Alert variant="destructive">
              <AlertDescription>{preview.error}</AlertDescription>
            </Alert>
          ) : (
            <div className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 px-3 py-2 text-[13px] leading-relaxed">
              {preview?.detail ? preview.detail.body || "This page has no text." : "Loading the page…"}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
