"use client";

import { useState } from "react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { apiClient } from "@/lib/api-client";

type Runbook = { id: string; title: string; application: string | null; markdown: string };

/** One runbook line with its **bold**, *italic* and `code` shown as such. */
function inline(line: string) {
  return line.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/).map((part, i) =>
    i % 2 === 0 ? (
      part
    ) : part.startsWith("**") ? (
      <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
    ) : part.startsWith("`") ? (
      <code key={i} className="rounded bg-muted px-1 font-mono text-[0.9em]">{part.slice(1, -1)}</code>
    ) : (
      <em key={i}>{part.slice(1, -1)}</em>
    ),
  );
}

const BULLET = /^- /;
const NUMBER = /^\d+\. /;

/** A runbook section as text: paragraphs, bullet lists and numbered steps.
 *  shortcut: only the markdown the runbooks use (no tables, links or nested lists); a markdown library when they need more. */
function RunbookText({ markdown }: { markdown: string }) {
  const lines = markdown.split("\n").filter((line) => line.trim() && line.trim() !== "---");
  const blocks: React.ReactNode[] = [];
  for (let i = 0; i < lines.length; ) {
    const marker = [BULLET, NUMBER].find((m) => m.test(lines[i]));
    if (!marker) {
      const heading = /^\*\*[^*]+\*\*$/.test(lines[i]); // "**Symptoms**" on its own line
      blocks.push(<p key={i} className={heading ? "mt-2 first:mt-0" : undefined}>{inline(lines[i])}</p>);
      i++;
      continue;
    }
    const start = i;
    while (i < lines.length && marker.test(lines[i])) i++;
    const items = lines.slice(start, i).map((line, n) => <li key={n}>{inline(line.replace(marker, ""))}</li>);
    blocks.push(
      marker === BULLET ? (
        <ul key={start} className="flex list-disc flex-col gap-1 pl-5">{items}</ul>
      ) : (
        <ol key={start} className="flex list-decimal flex-col gap-1 pl-5">{items}</ol>
      ),
    );
  }
  return <div className="flex flex-col gap-2 break-words">{blocks}</div>;
}

/** A runbook id that opens the runbook over the page: a persona may only open the pages in their menu.
 *  `panel` opens it on the right, full height, so the ticket behind stays in view. */
export function RunbookButton({ id, label, panel = false }: { id: string; label?: string; panel?: boolean }) {
  const [open, setOpen] = useState(false);
  const [runbook, setRunbook] = useState<Runbook | null>(null);
  const [failed, setFailed] = useState(false);

  const show = () => {
    setOpen(true);
    if (runbook) return;
    setFailed(false);
    apiClient<Runbook>(`/runbooks/${encodeURIComponent(id)}`)
      .then(setRunbook)
      .catch(() => setFailed(true));
  };

  return (
    <>
      {label ? (
        <Button variant="secondary" onClick={show}>
          {label}
        </Button>
      ) : (
        <Button variant="link" size="xs" className="px-0 font-mono text-foreground underline" onClick={show}>
          {id}
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className={cn(
            "sm:max-w-2xl",
            panel &&
              "top-0 right-0 left-auto flex h-full max-h-none w-full max-w-[460px] translate-x-0 translate-y-0 flex-col overflow-y-auto rounded-none border-y-0 border-r-0 sm:max-w-[460px]"
          )}
        >
          <DialogHeader>
            <DialogTitle>{runbook?.title ?? id}</DialogTitle>
            <DialogDescription>
              {runbook
                ? [runbook.id, runbook.application, "from the knowledge base"].filter(Boolean).join(" · ")
                : failed
                  ? "Couldn't open this runbook. Close this panel and try again shortly."
                  : "Loading…"}
            </DialogDescription>
          </DialogHeader>
          {runbook && <RunbookText markdown={runbook.markdown} />}
          {!runbook && !failed && (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4" />
              <Skeleton className="h-4" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
