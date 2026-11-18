"use client";

import { Fragment, useId, useState } from "react";
import Link from "next/link";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { usePerson } from "@/lib/view-as";
import { knowledgeService } from "@/services/knowledge-service";
import { DRAFT_REJECT_REASONS, DraftFields, KBDraft, KBDraftReview } from "@/types/knowledge";
import { Download, ExternalLink, Upload } from "lucide-react";

const GAP = /(\[expert to add\b[^\]]*\])/i; // what the backend refuses to approve
const SELECT =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

const fields = (d: KBDraft): DraftFields => ({
  title: d.title, symptoms: d.symptoms, root_cause: d.root_cause, resolution_steps: d.resolution_steps, escalation: d.escalation,
});
const hasGap = (d: DraftFields) => Object.values(d).flat().some((v) => GAP.test(v));
const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

/** Text with every "[expert to add]" marked, so the expert sees what is missing. */
function Gapped({ text }: { text: string }) {
  return (
    <>
      {text.split(GAP).map((part, i) =>
        GAP.test(part) ? (
          <mark key={i} className="rounded bg-accent px-1 font-semibold text-primary">
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

/** The expert's own text; it is approved when saved. Lists take one item per line. */
function EditDialog({ draft, busy, onSave }: { draft: KBDraft; busy: boolean; onSave: (f: DraftFields) => void }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    title: draft.title,
    symptoms: draft.symptoms.join("\n"),
    root_cause: draft.root_cause,
    resolution_steps: draft.resolution_steps.join("\n"),
    escalation: draft.escalation,
  });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [key]: e.target.value });
  const box = (key: keyof typeof form, label: string, rows: number) => (
    <div className="flex flex-col gap-1">
      <label htmlFor={`${id}-${key}`} className="font-medium">
        {label}
      </label>
      <Textarea id={`${id}-${key}`} rows={rows} value={form[key]} onChange={set(key)} />
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)} disabled={busy}>
        Edit and approve
      </Button>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit the draft for {draft.application}</DialogTitle>
          <DialogDescription>
            Replace every [expert to add]. No names, phone numbers or emails: the same checks as the draft apply.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-[13px]">
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-title`} className="font-medium">
              Title
            </label>
            <Input id={`${id}-title`} value={form.title} onChange={set("title")} />
          </div>
          {box("symptoms", "Symptoms, one per line", 3)}
          {box("root_cause", "Root cause", 3)}
          {box("resolution_steps", "Resolution steps, one per line", 5)}
          {box("escalation", "Escalation", 2)}
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="secondary" />}>Cancel</DialogClose>
          <Button
            disabled={busy}
            onClick={() =>
              onSave({ ...form, symptoms: lines(form.symptoms), resolution_steps: lines(form.resolution_steps) })
            }
          >
            {busy ? "Saving…" : "Save and approve"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RejectDialog({ busy, onReject }: { busy: boolean; onReject: (reason: KBDraftReview["reason_code"], note: string) => void }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<KBDraftReview["reason_code"] | "">("");
  const [note, setNote] = useState("");
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)} disabled={busy}>
        Reject
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject this draft</DialogTitle>
          <DialogDescription>It will not become an article. The reason helps tune the agent.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-[13px]">
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-r`} className="font-medium">
              Why
            </label>
            <select id={`${id}-r`} className={SELECT} value={reason} onChange={(e) => setReason(e.target.value as typeof reason)}>
              <option value="">Pick a reason</option>
              {DRAFT_REJECT_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-n`} className="font-medium">
              Note (optional)
            </label>
            <Textarea id={`${id}-n`} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="secondary" />}>Cancel</DialogClose>
          <Button variant="destructive" disabled={busy || !reason} onClick={() => reason && onReject(reason, note.trim())}>
            Reject
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** One drafted article: what it says, where it came from, and the expert's decision. */
export function DraftCard({ draft, onDone }: { draft: KBDraft; onDone: () => void }) {
  const person = usePerson();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const gaps = hasGap(fields(draft));

  const act = async (call: () => Promise<unknown>, failed: string) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : failed);
    } finally {
      setBusy(false);
    }
  };
  const send = (body: Omit<KBDraftReview, "reviewer">) =>
    act(() => knowledgeService.review(draft.id, { ...body, reviewer: person }), "Couldn't save the decision");
  const publish = () => act(() => knowledgeService.publish(draft.id), "Couldn't publish to Confluence");

  return (
    <li className="flex flex-col gap-2 border-b border-border px-4 py-3 text-[13px] last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono font-semibold">{draft.kb_id ?? "DRAFT"}</span>
        <span className="min-w-0 break-words font-semibold">
          <Gapped text={draft.title} />
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {[draft.application, draft.reviewer && `${draft.status} by ${draft.reviewer}`, draft.reason_code?.replace(/_/g, " ")]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-4 gap-y-1.5">
        <dt className="text-muted-foreground">Symptoms</dt>
        <dd>
          <ul className="list-disc pl-5">
            {draft.symptoms.map((s) => (
              <li key={s} className="break-words">
                <Gapped text={s} />
              </li>
            ))}
          </ul>
        </dd>
        <dt className="text-muted-foreground">Root cause</dt>
        <dd className="break-words">
          <Gapped text={draft.root_cause} />
        </dd>
        <dt className="text-muted-foreground">Steps</dt>
        <dd>
          <ol className="list-decimal pl-5">
            {draft.resolution_steps.map((s) => (
              <li key={s} className="break-words">
                <Gapped text={s} />
              </li>
            ))}
          </ol>
        </dd>
        <dt className="text-muted-foreground">Escalation</dt>
        <dd className="break-words">
          <Gapped text={draft.escalation} />
        </dd>
        <dt className="text-muted-foreground">Drafted from</dt>
        <dd className="flex flex-wrap gap-x-2">
          {draft.source_ticket_ids.map((t) => (
            <Link key={t} href={`/tickets/${encodeURIComponent(t)}`} className="font-mono text-primary underline-offset-4 hover:underline">
              {t}
            </Link>
          ))}
        </dd>
      </dl>
      <div className="flex flex-wrap items-center gap-2">
        {draft.status === "draft" && (
          <>
            <Button size="sm" onClick={() => send({ action: "approved" })} disabled={busy || gaps}>
              Approve
            </Button>
            <EditDialog draft={draft} busy={busy} onSave={(f) => send({ action: "edited", ...f })} />
            <RejectDialog busy={busy} onReject={(reason_code, note) => send({ action: "rejected", reason_code, note: note || undefined })} />
          </>
        )}
        {draft.status === "approved" &&
          (draft.confluence_url ? (
            <a href={draft.confluence_url} target="_blank" rel="noreferrer" className={buttonVariants({ size: "sm", variant: "secondary" })}>
              <ExternalLink />
              Open in Confluence
            </a>
          ) : (
            <Button size="sm" onClick={publish} disabled={busy}>
              <Upload />
              {busy ? "Publishing…" : "Publish to Confluence"}
            </Button>
          ))}
        {draft.status !== "rejected" && (
          <a href={knowledgeService.exportUrl(draft.id)} download className={buttonVariants({ size: "sm", variant: "ghost" })}>
            <Download />
            Markdown
          </a>
        )}
        {draft.status === "draft" && gaps && <span className="text-xs text-muted-foreground">Fill in every [expert to add] to approve: use Edit.</span>}
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertDescription className="break-words">{error}</AlertDescription>
        </Alert>
      )}
    </li>
  );
}
