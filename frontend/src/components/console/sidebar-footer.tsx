"use client";

import { useCallback, useEffect, useState } from "react";
import { Code2, LoaderCircle, RefreshCw, RotateCcw } from "lucide-react";
import { cn } from "cn";
import { ResetDemoButton } from "@/components/console/reset-demo-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useViewAs } from "@/lib/view-as";
import { jiraService } from "@/services/jira-service";

/** "14:05" today, "yesterday 14:05", else "18 Nov 14:05", so an old sync doesn't look fresh. */
const time = (iso: string) => {
  const d = new Date(iso);
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days === 0) return hm;
  if (days === 1) return `yesterday ${hm}`;
  return `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${hm}`;
};

const footerItem =
  "flex h-8 w-full items-center justify-start gap-2 rounded-lg px-3 text-xs font-medium text-sidebar-foreground hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar focus-visible:outline-none";

/** Pinned under the menu: when Jira last synced (with Sync now), the API docs, and the demo reset for admins. */
export function SidebarFooter({ onNavigate }: { onNavigate?: () => void }) {
  const isAdmin = useViewAs() === "admin";
  const [last, setLast] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(
    () =>
      jiraService.getSyncs(1).then(
        ([run]) => setLast(run?.finished_at ?? run?.started_at ?? null),
        () => setLast(null) // no line without an answer
      ),
    []
  );
  useEffect(() => {
    load();
  }, [load]);

  const syncNow = () => {
    setSyncing(true);
    setFailed(false);
    jiraService
      .syncNow()
      .then(load, () => setFailed(true))
      .finally(() => setSyncing(false));
  };

  return (
    <div className="flex shrink-0 flex-col gap-2.5 border-t border-sidebar-border pt-3">
      <div className="flex flex-col gap-2 px-3">
        {last && (
          <span className="flex items-center gap-2 text-[11px] text-sidebar-foreground">
            <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-sidebar-foreground" />
            <span>
              <span className="font-semibold">Jira</span> · last sync {time(last)}
            </span>
          </span>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={syncNow}
          disabled={syncing}
          className="h-7 rounded-full border border-sidebar-foreground/60 text-[11px] text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground"
        >
          {syncing ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
          {syncing ? "Syncing…" : "Sync now"}
        </Button>
        {failed && (
          <span role="alert" className="text-[11px] text-sidebar-foreground">
            The sync failed. Try again, or check Settings › Jira.
          </span>
        )}
      </div>
      <div className="flex flex-col gap-0.5 border-t border-sidebar-border pt-2.5">
        <a href="/docs" target="_blank" rel="noopener noreferrer" onClick={onNavigate} className={footerItem}>
          <Code2 className="size-3.5 shrink-0" aria-hidden="true" />
          API docs
        </a>
        {isAdmin && (
          <ResetDemoButton variant="ghost" className={cn(footerItem, "rounded-lg hover:text-sidebar-foreground")}>
            <RotateCcw className="size-3.5" aria-hidden="true" />
            <span className="flex-1 text-left">Reset demo</span>
            <Badge variant="outline" className="h-4 border-sidebar-foreground/60 px-1.5 text-[9px] text-sidebar-foreground">
              Demo
            </Badge>
          </ResetDemoButton>
        )}
      </div>
    </div>
  );
}
