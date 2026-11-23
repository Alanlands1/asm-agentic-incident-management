"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Check, LoaderCircle, Send, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { usePerson } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { AgentRun, PipelineTicket } from "@/types/pipeline";
import { cn } from "cn";

type Proposal = { root_cause: string; steps: string[]; check: string };

/**
 * Work out a fix with the AI assistant (POST /tickets/{id}/chat). Open by itself when no runbook covers the ticket.
 * A proposal can become the suggested fix; the usual loop follows (try it, say if it worked, closure note).
 */
export function FixChat({ ticket, noRunbook, onDone }: { ticket: PipelineTicket; noRunbook: boolean; onDone: () => unknown }) {
  const person = usePerson();
  const [open, setOpen] = useState(noRunbook);
  const [message, setMessage] = useState("");
  const [asking, setAsking] = useState<string | null>(null); // the message being answered
  const [using, setUsing] = useState<number | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const turns = ticket.agent_runs.filter((r) => r.agent === "fix_chat");
  const fix = ticket.agent_runs.findLast((r) => r.agent === "resolution");
  const usedId = fix?.output.source === "chat" ? (fix.output.chat_run_id as number) : null;
  const canUse = ["reviewed", "needs_lead"].includes(ticket.pipeline_status) && ticket.status !== "closed";

  useEffect(() => {
    if (open) end.current?.scrollIntoView({ block: "nearest" });
  }, [open, turns.length, asking]);

  const send = () => {
    const text = message.trim();
    if (!text) return;
    setAsking(text);
    setMessage("");
    setFailed(null);
    pipelineService
      .chat(ticket.id, { message: text, author: person })
      .then(onDone)
      .catch((e: unknown) => {
        setFailed(e instanceof Error ? e.message : "The assistant gave no answer. Try again.");
        setMessage(text);
      })
      .finally(() => setAsking(null));
  };
  const use = (run: AgentRun) => {
    setUsing(run.id);
    setFailed(null);
    pipelineService
      .useChatFix(ticket.id, { run_id: run.id, reviewer: person })
      .then(onDone)
      .catch((e: unknown) => setFailed(e instanceof Error ? e.message : "Couldn't use that fix"))
      .finally(() => setUsing(null));
  };

  if (!open)
    return (
      <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
          <Sparkles />
          Ask the AI assistant{turns.length ? ` · ${turns.length}` : ""}
        </Button>
        <span className="text-xs text-muted-foreground">A second opinion on the fix, or help when the runbook steps don&rsquo;t fit.</span>
      </div>
    );

  return (
    <section aria-label="AI assistant" className="flex flex-col gap-3 border-t border-border bg-muted/40 px-4 py-3 animate-in fade-in duration-300">
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true" className="flex size-7 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Bot className="size-4" />
        </span>
        <h3 className="text-sm font-semibold">{noRunbook ? "No runbook covers this. Work it out with the AI assistant" : "AI assistant"}</h3>
        <Badge variant="outline" className="ml-auto">AI suggestion, not from a runbook</Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        Tell it what you see: the error, the log line, when it started, what changed. Personal details are masked before the model reads the ticket.
        {canUse ? " Use a proposed fix to make it the suggested fix; then try it and say if it worked." : ""}
      </p>

      {turns.length > 0 && (
        <ol role="list" className="flex flex-col gap-2.5">
          {turns.map((t) => {
            const proposal = t.output.fix as Proposal | null;
            return (
              <li key={t.id} className="flex flex-col gap-2">
                <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-card px-3 py-2 whitespace-pre-wrap break-words shadow-[0_0_0_1px_var(--border)]">
                  <span className="block text-[11px] font-medium text-muted-foreground">{String(t.output.asked_by ?? "Engineer")}</span>
                  {String(t.output.question ?? "")}
                </p>
                <div className="mr-auto flex max-w-[92%] flex-col gap-2 rounded-2xl rounded-bl-sm bg-selected px-3 py-2">
                  <p className="whitespace-pre-wrap break-words">
                    <span className="block text-[11px] font-medium text-primary">AI assistant</span>
                    {String(t.output.reply ?? "")}
                  </p>
                  {proposal && (
                    <div className={cn("flex flex-col gap-1.5 rounded-xl border bg-card px-3 py-2.5", usedId === t.id ? "border-p3" : "border-border")}>
                      <p className="font-mono text-[10.5px] font-medium tracking-[0.08em] text-muted-foreground uppercase">Proposed fix</p>
                      <p>
                        <span className="font-semibold">Cause: </span>
                        {proposal.root_cause}
                      </p>
                      <ol className="flex list-decimal flex-col gap-0.5 pl-5">
                        {proposal.steps.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ol>
                      <p>
                        <span className="font-semibold">Check: </span>
                        {proposal.check}
                      </p>
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        {usedId === t.id ? (
                          <Badge variant="outline" className="border-p3 text-p3">
                            <Check aria-hidden="true" />
                            The suggested fix
                          </Badge>
                        ) : (
                          canUse && (
                            <Button size="sm" disabled={using !== null || asking !== null} onClick={() => use(t)}>
                              {using === t.id ? <LoaderCircle className="animate-spin" /> : <Check />}
                              Use as the fix
                            </Button>
                          )
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {asking && (
        <div className="flex flex-col gap-2">
          <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-card px-3 py-2 whitespace-pre-wrap break-words shadow-[0_0_0_1px_var(--border)]">{asking}</p>
          <p role="status" className="mr-auto flex items-center gap-2 rounded-2xl rounded-bl-sm bg-selected px-3 py-2 text-primary">
            <LoaderCircle className="size-3.5 animate-spin" />
            The assistant is thinking…
          </p>
        </div>
      )}
      <div ref={end} />

      <div className="flex flex-col gap-2">
        <label htmlFor="fix-chat" className="sr-only">
          Message to the AI assistant
        </label>
        <Textarea
          id="fix-chat"
          rows={2}
          value={message}
          placeholder={turns.length ? "Answer the assistant, or ask something else…" : "What do you see? E.g. the error message, a log line, what changed before it started."}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send();
          }}
          disabled={asking !== null}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={asking !== null || !message.trim()} onClick={send}>
            {asking ? <LoaderCircle className="animate-spin" /> : <Send />}
            Send
          </Button>
          <span className="text-xs text-muted-foreground">Ctrl+Enter sends</span>
          {!noRunbook && (
            <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setOpen(false)}>
              Hide
            </Button>
          )}
        </div>
        {failed && (
          <p role="alert" className="text-xs font-medium text-destructive">
            {failed}
          </p>
        )}
      </div>
    </section>
  );
}
