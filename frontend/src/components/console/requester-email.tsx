"use client";

import { useId, useState } from "react";
import { Check, Copy, LoaderCircle, Mail, Send } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { usePerson } from "@/lib/view-as";
import { pipelineService } from "@/services/pipeline-service";
import { PipelineTicket } from "@/types/pipeline";

/**
 * A draft email telling the requester their ticket is resolved, written from the saved closure note. Nothing is sent
 * on its own: the engineer edits it, then opens it in their email app, copies it, or posts it as a reply on the source.
 */
export function RequesterEmail({
  ticket,
  ready,
  toJira,
  source,
  onSent,
}: {
  ticket: PipelineTicket;
  ready: string | null; // null when a complete closure note is saved; otherwise why a draft can't be written yet
  toJira: boolean;
  source: string;
  onSent: () => unknown;
}) {
  const id = useId();
  const person = usePerson();
  const [email, setEmail] = useState<{ subject: string; body: string } | null>(null);
  const [doing, setDoing] = useState<"draft" | "send" | null>(null);
  const [done, setDone] = useState<"subject" | "body" | "all" | "sent" | null>(null); // the last thing copied or sent
  const [error, setError] = useState<string | null>(null);

  const run = (what: "draft" | "send", work: () => Promise<unknown>) => {
    setDoing(what);
    setError(null);
    setDone(null);
    work()
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Something went wrong. Try again."))
      .finally(() => setDoing(null));
  };
  const draft = () => run("draft", async () => setEmail(await pipelineService.draftEmail(ticket.id)));
  const send = () =>
    run("send", async () => {
      await pipelineService.addComment(ticket.id, person, email!.body.trim(), true);
      setDone("sent");
      onSent();
    });
  const copy = (what: "subject" | "body" | "all") =>
    navigator.clipboard
      .writeText(what === "subject" ? email!.subject : what === "body" ? email!.body : `Subject: ${email!.subject}\n\n${email!.body}`)
      .then(() => setDone(what), () => setError("Copying is blocked in this browser. Select the text instead."));
  // A copy button beside each field, so the subject and the message paste into their own boxes in the email app.
  const copyButton = (what: "subject" | "body", label: string) => (
    <Button size="xs" variant="ghost" disabled={!email?.[what].trim()} onClick={() => copy(what)} aria-label={`Copy ${label.toLowerCase()}`}>
      {done === what ? <Check /> : <Copy />}
      {done === what ? "Copied" : "Copy"}
    </Button>
  );
  const mailto =
    email && ticket.reporter_email
      ? `mailto:${ticket.reporter_email}?subject=${encodeURIComponent(email.subject)}&body=${encodeURIComponent(email.body)}`
      : null;

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">Email to requester</span>
        <Button size="sm" variant="secondary" disabled={ready !== null || doing !== null} onClick={draft}>
          {doing === "draft" ? <LoaderCircle className="animate-spin" /> : <Mail />}
          {doing === "draft" ? "Drafting…" : email ? "Redraft" : "Draft email"}
        </Button>
        <span className="text-xs text-muted-foreground">
          {ready ?? (email ? "Review and edit before sending. Nothing is sent automatically." : "Written in plain language from the saved closure note.")}
        </span>
      </div>
      {email && (
        <div className="flex flex-col gap-2 rounded-xl bg-muted px-3 py-2.5 animate-in fade-in duration-300">
          <p className="text-xs text-muted-foreground">
            To: {ticket.reporter_name ?? "Requester"}
            {ticket.reporter_email ? ` <${ticket.reporter_email}>` : ""}
          </p>
          <div className="flex items-center justify-between gap-2">
            <label htmlFor={`${id}-subject`} className="text-xs font-semibold">
              Subject
            </label>
            {copyButton("subject", "Subject")}
          </div>
          <Input id={`${id}-subject`} value={email.subject} onChange={(e) => setEmail({ ...email, subject: e.target.value })} disabled={doing !== null} />
          <div className="flex items-center justify-between gap-2">
            <label htmlFor={`${id}-body`} className="text-xs font-semibold">
              Message
            </label>
            {copyButton("body", "Message")}
          </div>
          <Textarea id={`${id}-body`} rows={9} value={email.body} onChange={(e) => setEmail({ ...email, body: e.target.value })} disabled={doing !== null} />
          <div className="flex flex-wrap items-center gap-2">
            {mailto && (
              <a href={mailto} className={buttonVariants({ size: "sm" })}>
                <Mail />
                Open in email app
              </a>
            )}
            <Button size="sm" variant="secondary" disabled={doing !== null || !email.body.trim()} onClick={() => copy("all")}>
              {done === "all" ? <Check /> : <Copy />}
              {done === "all" ? "Copied" : "Copy all"}
            </Button>
            {toJira && (
              <Button size="sm" variant="secondary" disabled={doing !== null || done === "sent" || !email.body.trim()} onClick={send}>
                {doing === "send" ? <LoaderCircle className="animate-spin" /> : done === "sent" ? <Check /> : <Send />}
                {done === "sent" ? `Posted on ${source}` : `Post as reply on ${source}`}
              </Button>
            )}
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
