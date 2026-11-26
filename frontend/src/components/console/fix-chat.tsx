"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bot, Check, CircleCheck, LoaderCircle, RotateCw, Search, Send, Sparkles, Trash2 } from "lucide-react";
import { RunbookButton } from "@/components/console/runbook-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { usePerson } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { AgentRun, PipelineTicket } from "@/types/pipeline";
import { cn } from "cn";

type Proposal = { root_cause: string; steps: string[]; check: string };
/** What running an agent again from the chat did (backend: endpoints/tickets._chat_rerun). */
type Rerun = { agent: string; note: string; ran: boolean; detail?: string; run_id?: number | null };

const AGENT_NAMES: Record<string, string> = {
  data_quality: "Data Quality",
  triage: "Triage",
  resolution: "Resolution",
  closure_quality: "Closure Quality",
};

const OPEN_EVENT = "ams-assistant"; // sent by AskAssistant, heard by FixChat
const STARTERS = ["What should I check first?", "Has this happened before?", "Which runbook article fits?"];
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\bKB-[A-Z]+-\d+\b|\b(?:AMS|MBX|INC)-\d+\b)/g;
const BULLET = /^\s*[-*•]\s+/;
const NUMBER = /^\s*\d+[.)]\s+/;

const time = (iso: string) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const initials = (name: string) =>
  name
    .split(/[\s.@]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");

/** One line with `code`, **bold**, runbook ids (open the article) and ticket ids (go to the ticket). */
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(INLINE).map((part, i) =>
        i % 2 === 0 ? (
          <Fragment key={i}>{part}</Fragment>
        ) : part.startsWith("`") ? (
          <code key={i} className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[12px] break-all">
            {part.slice(1, -1)}
          </code>
        ) : part.startsWith("**") ? (
          <strong key={i} className="font-semibold">
            {part.slice(2, -2)}
          </strong>
        ) : part.startsWith("KB-") ? (
          <RunbookButton key={i} id={part} panel />
        ) : (
          <Link key={i} href={`/tickets/${encodeURIComponent(part)}`} className="font-mono text-[12px] font-medium text-primary underline-offset-4 hover:underline">
            {part}
          </Link>
        )
      )}
    </>
  );
}

/** The assistant's words as short paragraphs and lists. */
function Rich({ text }: { text: string }) {
  // Paragraphs, and list items merged into one list even with blank lines between them (models often write that).
  const blocks: { lines: string[]; marker?: RegExp }[] = [];
  for (const block of text.trim().split(/\n\s*\n/)) {
    const lines = block.split("\n").filter((l) => l.trim());
    const marker = [BULLET, NUMBER].find((m) => lines.length > 0 && lines.every((l) => m.test(l)));
    const last = blocks.at(-1);
    if (marker && last?.marker === marker) last.lines.push(...lines);
    else blocks.push({ lines, marker });
  }
  return (
    <div className="flex flex-col gap-2 leading-relaxed">
      {blocks.map(({ lines, marker }, b) => {
        if (marker) {
          const List = marker === NUMBER ? "ol" : "ul";
          return (
            <List key={b} className={cn("flex flex-col gap-1 pl-5", marker === NUMBER ? "list-decimal" : "list-disc")}>
              {lines.map((l, i) => (
                <li key={i} className="pl-0.5 marker:text-muted-foreground">
                  <Inline text={l.replace(marker, "")} />
                </li>
              ))}
            </List>
          );
        }
        return (
          <p key={b} className="break-words">
            {lines.map((l, i) => (
              <Fragment key={i}>
                {i > 0 && <br />}
                <Inline text={l} />
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

/** A proposed fix: the cause, numbered steps and how to check it, with Use as suggested fix. */
function ProposalCard({ proposal, used, action }: { proposal: Proposal; used: boolean; action: React.ReactNode }) {
  return (
    <div className={cn("flex flex-col gap-3 rounded-xl border bg-card p-3", used ? "border-2 border-p3" : "border-border")}>
      <p className="flex items-center gap-1.5 font-mono text-[10.5px] font-medium tracking-[0.08em] text-primary uppercase">
        <Sparkles className="size-3.5" aria-hidden="true" />
        Proposed fix
      </p>
      <div className="flex gap-2.5">
        <Search className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div>
          <p className="text-xs font-semibold text-muted-foreground">Likely cause</p>
          <Inline text={proposal.root_cause} />
        </div>
      </div>
      <ol role="list" className="flex flex-col gap-2">
        {proposal.steps.map((s, i) => (
          <li key={i} className="flex gap-2.5">
            <span aria-hidden="true" className="flex size-5 shrink-0 items-center justify-center rounded-full bg-selected text-[11px] font-semibold text-primary tabular-nums">
              {i + 1}
            </span>
            <span className="min-w-0 break-words">
              <span className="sr-only">Step {i + 1}: </span>
              <Inline text={s} />
            </span>
          </li>
        ))}
      </ol>
      <div className="flex gap-2.5 rounded-lg bg-muted px-2.5 py-2">
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-p3" aria-hidden="true" />
        <div>
          <p className="text-xs font-semibold text-muted-foreground">How to verify the fix</p>
          <Inline text={proposal.check} />
        </div>
      </div>
      {action && <div className="flex flex-wrap items-center gap-2">{action}</div>}
    </div>
  );
}

/** The row in the Resolution step that opens the assistant. */
export function AskAssistant({ noRunbook }: { noRunbook: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
      <Button size="sm" variant="secondary" onClick={() => window.dispatchEvent(new Event(OPEN_EVENT))}>
        <Sparkles />
        Ask the AI assistant
      </Button>
      <span className="text-xs text-muted-foreground">
        {noRunbook ? "No runbook covers this. Work out a fix with the AI assistant." : "Get a second opinion on the fix, or help when the runbook steps don’t apply."}
      </span>
    </div>
  );
}

/**
 * Work out a fix with the AI assistant (POST /tickets/{id}/chat), in a chat window that pops out over the bottom right
 * of the page; the ticket behind it stays usable. A proposal can become the suggested fix and the usual loop follows.
 */
export function FixChat({
  ticket,
  noRunbook,
  renderRun,
  onDone,
}: {
  ticket: PipelineTicket;
  noRunbook: boolean;
  /** One stored agent result, as the ticket page shows it: the chat prints these, it does not retype them. */
  renderRun: (run: AgentRun) => React.ReactNode;
  onDone: () => unknown;
}) {
  const person = usePerson();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [asking, setAsking] = useState<string | null>(null); // the message being answered
  const [using, setUsing] = useState<number | null>(null);
  const [clearing, setClearing] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const turns = ticket.agent_runs.filter((r) => r.agent === "fix_chat" && !r.output.cleared);
  const fix = ticket.agent_runs.findLast((r) => r.agent === "resolution");
  const usedId = fix?.output.source === "chat" ? (fix.output.chat_run_id as number) : null;
  const canUse = ["reviewed", "needs_lead"].includes(ticket.pipeline_status) && ticket.status !== "closed";
  const stored = (id?: number | null) => {
    const run = ticket.agent_runs.find((r) => r.id === id);
    return run ? <div className="overflow-hidden rounded-xl border border-border bg-card">{renderRun(run)}</div> : null;
  };

  // Keep the newest message in view inside the box; the page itself does not move.
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [open, turns.length, asking]);

  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, show);
    return () => window.removeEventListener(OPEN_EVENT, show);
  }, []);

  const send = (text = message.trim()) => {
    if (!text) return;
    setAsking(text);
    setMessage("");
    setFailed(null);
    pipelineService
      .chat(ticket.id, { message: text, author: person })
      .then(onDone)
      .catch((e: unknown) => {
        setFailed(e instanceof Error ? e.message : "The assistant did not respond. Try again.");
        setMessage(text);
      })
      .finally(() => setAsking(null));
  };
  const clear = () => {
    setClearing(true);
    setFailed(null);
    pipelineService
      .clearChat(ticket.id)
      .then(onDone)
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't clear the chat. Try again."))
      .finally(() => setClearing(false));
  };
  const use = (run: AgentRun) => {
    setUsing(run.id);
    setFailed(null);
    pipelineService
      .useChatFix(ticket.id, { run_id: run.id, reviewer: person })
      .then(onDone)
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't apply that fix. Try again."))
      .finally(() => setUsing(null));
  };

  return (
    <>
      {!open && (
        <Button className="fixed right-4 bottom-4 z-30 rounded-full shadow-[0_8px_24px_-8px_rgba(22,19,14,0.45)]" onClick={() => setOpen(true)}>
          <Bot />
          AI assistant{turns.length ? ` · ${turns.length}` : ""}
        </Button>
      )}
      {/* Not modal: the ticket stays readable and usable while the chat is open; only its close button closes it. */}
      <Dialog open={open} onOpenChange={setOpen} modal={false} disablePointerDismissal>
        <DialogContent
          showOverlay={false}
          className="top-auto right-4 bottom-4 left-auto flex h-[min(42rem,calc(100dvh-2rem))] w-[28rem] translate-x-0 translate-y-0 flex-col gap-3 overflow-hidden rounded-2xl p-3 sm:max-w-[28rem]"
        >
      <div className="flex flex-wrap items-center gap-2 pr-8">
        <span aria-hidden="true" className="flex size-8 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Bot className="size-4" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <DialogTitle>{noRunbook ? "No runbook covers this. Work out a fix with the AI assistant" : "AI assistant"}</DialogTitle>
          <DialogDescription className="text-xs">Uses the ticket, team notes, similar closed tickets and the knowledge base. Personal data is masked.</DialogDescription>
        </div>
        <Badge variant="outline">AI suggestion, not from a runbook</Badge>
      </div>

      <div ref={box} aria-live="polite" className="scroll-thin flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain rounded-xl border border-border bg-card p-3">
        {turns.length === 0 && !asking && (
          <div className="m-auto flex flex-col items-center gap-3 py-4 text-center">
            <Sparkles className="size-6 text-primary" aria-hidden="true" />
            <p className="max-w-sm text-muted-foreground">Describe what you see: the error, a log line, when it started, what changed. Or start with:</p>
            <div className="flex flex-wrap justify-center gap-2">
              {STARTERS.map((s) => (
                <Button key={s} size="sm" variant="secondary" onClick={() => send(s)}>
                  {s}
                </Button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t) => {
          const proposal = t.output.fix as Proposal | null;
          const shown = Object.values((t.output.shown ?? {}) as Record<string, number>);
          const rerun = t.output.rerun as Rerun | null | undefined;
          const who = String(t.output.asked_by ?? "Engineer");
          return (
            <div key={t.id} className="flex flex-col gap-3">
              <div className="ml-auto flex max-w-[85%] items-end gap-2">
                <div className="flex flex-col items-end gap-1">
                  <span className="text-[11px] text-muted-foreground">
                    {who} · {time(t.created_at)}
                  </span>
                  <p className="rounded-2xl rounded-br-sm bg-primary px-3 py-2 whitespace-pre-wrap break-words text-primary-foreground">{String(t.output.question ?? "")}</p>
                </div>
                <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center rounded-full bg-foreground text-[10px] font-semibold text-background">
                  {initials(who)}
                </span>
              </div>
              <div className="mr-auto flex max-w-[92%] items-start gap-2">
                <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center rounded-full bg-selected text-primary">
                  <Bot className="size-4" />
                </span>
                <div className="flex min-w-0 flex-col gap-2">
                  <span className="text-[11px] text-muted-foreground">AI assistant · {time(t.created_at)}</span>
                  <div className="rounded-2xl rounded-tl-sm bg-muted px-3 py-2.5">
                    <Rich text={String(t.output.reply ?? "")} />
                  </div>
                  {shown.map((id) => (
                    <Fragment key={id}>{stored(id)}</Fragment>
                  ))}
                  {rerun && (
                    <div className="flex flex-col gap-2">
                      <p className="flex flex-wrap items-center gap-1.5 text-xs font-semibold">
                        <RotateCw className="size-3.5 text-primary" aria-hidden="true" />
                        {rerun.ran
                          ? rerun.run_id
                            ? `${AGENT_NAMES[rerun.agent] ?? rerun.agent} ran again`
                            : `${AGENT_NAMES[rerun.agent] ?? rerun.agent} is running again. The new result will appear in its step.`
                          : `${AGENT_NAMES[rerun.agent] ?? rerun.agent} did not run: ${rerun.detail ?? "not available now"}.`}
                      </p>
                      {rerun.ran && rerun.note && <p className="text-xs break-words text-muted-foreground">Saved as a note for the agents: {rerun.note}</p>}
                      {rerun.ran && stored(rerun.run_id)}
                    </div>
                  )}
                  {proposal && (
                    <ProposalCard
                      proposal={proposal}
                      used={usedId === t.id}
                      action={
                        usedId === t.id ? (
                          <Badge variant="outline" className="border-p3 text-p3">
                            <Check aria-hidden="true" />
                            Current suggested fix
                          </Badge>
                        ) : (
                          canUse && (
                            <Button size="sm" disabled={using !== null || asking !== null} onClick={() => use(t)}>
                              {using === t.id ? <LoaderCircle className="animate-spin" /> : <Check />}
                              Use as suggested fix
                            </Button>
                          )
                        )
                      }
                    />
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {asking && (
          <div className="flex flex-col gap-3">
            <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3 py-2 whitespace-pre-wrap break-words text-primary-foreground">{asking}</p>
            <div className="mr-auto flex items-center gap-2">
              <span aria-hidden="true" className="flex size-7 items-center justify-center rounded-full bg-selected text-primary">
                <Bot className="size-4" />
              </span>
              <p role="status" className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm bg-muted px-3 py-2.5 text-muted-foreground">
                <span className="sr-only">The assistant is thinking</span>
                {[0, 150, 300].map((d) => (
                  <span key={d} aria-hidden="true" className="size-1.5 animate-bounce rounded-full bg-primary" style={{ animationDelay: `${d}ms` }} />
                ))}
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="fix-chat" className="sr-only">
          Message to the AI assistant
        </label>
        <div className="flex items-end gap-2 rounded-xl border border-input bg-card p-1.5 focus-within:ring-2 focus-within:ring-ring">
          <Textarea
            id="fix-chat"
            rows={2}
            value={message}
            placeholder={turns.length ? "Reply to the assistant, or ask something else…" : "What do you see? The error message, a log line, what changed…"}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send();
            }}
            disabled={asking !== null}
            className="min-h-0 flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
          />
          <Button size="sm" disabled={asking !== null || !message.trim()} onClick={() => send()} aria-label="Send">
            {asking ? <LoaderCircle className="animate-spin" /> : <Send />}
            Send
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>Press Ctrl+Enter to send</span>
          {canUse && <span>· Select a proposed fix to make it the suggested fix, then apply it and confirm the outcome.</span>}
          {turns.length > 0 && (
            <Button size="xs" variant="ghost" className="ml-auto" disabled={clearing || asking !== null} onClick={clear}>
              {clearing ? <LoaderCircle className="animate-spin" /> : <Trash2 />}
              Clear chat
            </Button>
          )}
        </div>
        {failed && (
          <p role="alert" className="text-xs font-medium text-destructive">
            {failed}
          </p>
        )}
      </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
