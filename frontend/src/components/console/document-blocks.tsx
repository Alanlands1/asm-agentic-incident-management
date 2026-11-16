"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PriorityChip } from "@/components/console/priority-chip";
import { Hint, hintFor, humanize } from "@/components/console/document-hints";
import { Json } from "@/types/admin";
import { ChevronDown, ChevronRight, Plus, X } from "lucide-react";
import { cn } from "cn";

type Obj = { [key: string]: Json };
const isObj = (v: Json): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isScalar = (v: Json) => !isObj(v) && !Array.isArray(v);

const selectClass =
  "h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

type Kind = "scalar" | "list-scalar" | "list-object" | "map-scalar" | "map-list" | "map-object" | "object";

/** What a value looks like decides how it is edited: chips, cards, a grid of fields or one input. */
function kindOf(v: Json, hint: Hint): Kind {
  if (Array.isArray(v)) {
    if (v.length === 0) return isObj(hint.template ?? null) ? "list-object" : "list-scalar";
    return v.every(isScalar) ? "list-scalar" : "list-object";
  }
  if (isObj(v)) {
    const vals = Object.values(v);
    if (vals.length === 0) return hint.template === undefined ? "map-scalar" : Array.isArray(hint.template) ? "map-list" : "map-object";
    if (vals.every(isObj)) return "map-object";
    if (vals.every(Array.isArray)) return "map-list";
    if (vals.every(isScalar)) return "map-scalar";
    return "object";
  }
  return "scalar";
}

/** The same shape as `v` with every value emptied: what "Add" creates when there is no template. */
function blank(v: Json): Json {
  if (Array.isArray(v)) return [];
  if (isObj(v)) return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, blank(x)]));
  if (typeof v === "number") return 0;
  if (typeof v === "boolean") return false;
  return v === null ? null : "";
}

const str = (v: Json | undefined) => (typeof v === "string" && v ? v : null);
const looksLikePattern = (s: string) => /[\\^$|]/.test(s);

interface Ctx {
  doc: string;
}

/** Whole document as blocks. The root is an object: one section per top-level key, or one card per entry. */
export function DocumentBlocks({ doc, value, onChange }: { doc: string; value: Json; onChange: (v: Json) => void }) {
  if (!isObj(value)) {
    return <p className="text-muted-foreground">This file is not a set of named entries, so it can only be edited as YAML.</p>;
  }
  const ctx = { doc };
  const root = hintFor(doc, []);
  if (kindOf(value, root) === "map-object") {
    return <ItemCards ctx={ctx} hp={[]} entries={Object.entries(value)} keyed onChange={(e) => onChange(Object.fromEntries(e))} template={root.template} />;
  }
  return (
    <div className="flex flex-col gap-4">
      {Object.entries(value).map(([key, v]) => {
        const hint = hintFor(doc, [key]);
        return (
          <section key={key} className="rounded-[14px] border border-border bg-card">
            <div className="flex flex-col gap-0.5 border-b border-border px-4 py-3">
              <h3 className="text-sm font-semibold">{hint.label ?? humanize(key)}</h3>
              {hint.help && <p className="text-xs text-muted-foreground">{hint.help}</p>}
            </div>
            <div className="px-4 py-3">
              <Control ctx={ctx} hp={[key]} value={v} onChange={(x) => onChange({ ...value, [key]: x })} />
            </div>
          </section>
        );
      })}
    </div>
  );
}

function Control({ ctx, hp, value, onChange, siblings }: { ctx: Ctx; hp: string[]; value: Json; onChange: (v: Json) => void; siblings?: Obj[] }) {
  const hint = hintFor(ctx.doc, hp);
  switch (kindOf(value, hint)) {
    case "scalar":
      return <ScalarInput value={value} onChange={onChange} hint={hint} />;
    case "list-scalar":
      return <ChipList items={value as Json[]} onChange={onChange} />;
    case "list-object":
      return (
        <ItemCards
          ctx={ctx}
          hp={hp}
          entries={(value as Json[]).map((v, i) => [String(i), v])}
          onChange={(e) => onChange(e.map(([, v]) => v))}
          template={hint.template}
        />
      );
    case "map-object":
      return <ItemCards ctx={ctx} hp={hp} entries={Object.entries(value as Obj)} keyed onChange={(e) => onChange(Object.fromEntries(e))} template={hint.template} />;
    case "map-scalar":
      return <FieldList ctx={ctx} hp={hp} obj={value as Obj} onChange={onChange} />;
    case "map-list":
      return <MapOfLists ctx={ctx} hp={hp} obj={value as Obj} onChange={onChange} template={hint.template} />;
    default:
      return <FieldList ctx={ctx} hp={hp} obj={value as Obj} onChange={onChange} siblings={siblings} />;
  }
}

/** Label + control per key. Scalars sit in a two-column grid; lists and objects get their own labelled block. */
function FieldList({ ctx, hp, obj, onChange, siblings }: { ctx: Ctx; hp: string[]; obj: Obj; onChange: (v: Json) => void; siblings?: Obj[] }) {
  const missing = siblings ? [...new Set(siblings.flatMap(Object.keys))].filter((k) => !(k in obj)) : [];
  const addField = (key: string) => {
    const from = siblings?.find((s) => key in s)?.[key] ?? "";
    onChange({ ...obj, [key]: hintFor(ctx.doc, [...hp, key]).template ?? blank(from) });
  };
  return (
    <div className="flex flex-col gap-3">
      {Object.entries(obj).map(([key, v]) => {
        const hint = hintFor(ctx.doc, [...hp, key]);
        const label = hint.label ?? (/^[1-5]$/.test(key) ? `P${key}` : humanize(key));
        const inline = isScalar(v) && !(typeof v === "string" && (hint.multiline || v.includes("\n") || v.length > 80));
        return (
          <div key={key} className={cn("grid gap-x-4 gap-y-1", inline && "sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)] sm:items-start")}>
            <div className={cn("flex flex-col", inline && "sm:pt-1.5")}>
              <span className="text-[13px] font-medium">{label}</span>
              {hint.help && <span className="text-xs text-muted-foreground">{hint.help}</span>}
            </div>
            <div className="flex min-w-0 items-start gap-2">
              <div className="min-w-0 flex-1">
                <Control ctx={ctx} hp={[...hp, key]} value={v} onChange={(x) => onChange({ ...obj, [key]: x })} />
              </div>
              {key === "priority" && typeof v === "number" && (
                <span className="pt-1">
                  <PriorityChip priority={v} />
                </span>
              )}
            </div>
          </div>
        );
      })}
      {missing.length > 0 && (
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Plus className="size-3.5" aria-hidden="true" />
          <select value="" onChange={(e) => e.target.value && addField(e.target.value)} className={selectClass} aria-label="Add a field">
            <option value="">Add a field…</option>
            {missing.map((k) => (
              <option key={k} value={k}>
                {hintFor(ctx.doc, [...hp, k]).label ?? humanize(k)}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

/** Named lists side by side: scope words, PII patterns, cross-application patterns. */
function MapOfLists({ ctx, hp, obj, onChange, template }: { ctx: Ctx; hp: string[]; obj: Obj; onChange: (v: Json) => void; template?: Json }) {
  const [newKey, setNewKey] = useState("");
  const add = () => {
    const k = newKey.trim();
    if (!k || k in obj) return;
    onChange({ ...obj, [k]: template ?? [] });
    setNewKey("");
  };
  return (
    <div className="flex flex-col gap-3">
      {Object.entries(obj).map(([key, v]) => {
        const hint = hintFor(ctx.doc, [...hp, key]);
        return (
          <div key={key} className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13px] font-medium">{hint.label ?? (template !== undefined ? key : humanize(key))}</span>
              {template !== undefined && (
                <Button variant="ghost" size="icon-xs" aria-label={`Remove ${key}`} onClick={() => onChange(Object.fromEntries(Object.entries(obj).filter(([k]) => k !== key)))}>
                  <X />
                </Button>
              )}
            </div>
            <Control ctx={ctx} hp={[...hp, key]} value={v} onChange={(x) => onChange({ ...obj, [key]: x })} />
          </div>
        );
      })}
      {template !== undefined && (
        <div className="flex items-center gap-2">
          <Input value={newKey} onChange={(e) => setNewKey(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())} placeholder="New group name" className="w-56" aria-label="New group name" />
          <Button variant="secondary" size="sm" onClick={add} disabled={!newKey.trim()}>
            <Plus data-icon="inline-start" /> Add group
          </Button>
        </div>
      )}
    </div>
  );
}

/** One card per rule, job or application. Closed: a one-line summary. Open: every field, editable. */
function ItemCards({
  ctx,
  hp,
  entries,
  keyed,
  onChange,
  template,
}: {
  ctx: Ctx;
  hp: string[];
  entries: [string, Json][];
  keyed?: boolean;
  onChange: (entries: [string, Json][]) => void;
  template?: Json;
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const siblings = entries.map(([, v]) => v).filter(isObj);
  const hint = hintFor(ctx.doc, hp);
  const singular = hint.item ?? (hint.label ?? humanize(hp[hp.length - 1] ?? "entry")).replace(/s$/, "").toLowerCase();

  const toggle = (k: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const add = () => {
    const value = template ?? (entries.length ? blank(entries[0][1]) : {});
    let key = String(entries.length);
    if (keyed) {
      key = "new";
      for (let i = 2; entries.some(([k]) => k === key); i++) key = `new_${i}`;
    }
    onChange([...entries, [key, value]]);
    setOpen((s) => new Set(s).add(key));
  };
  const rename = (from: string, to: string) => onChange(entries.map(([k, v]) => (k === from ? [to, v] : [k, v])));

  return (
    <div className="flex flex-col gap-2">
      {entries.length === 0 && <p className="text-xs text-muted-foreground">None yet.</p>}
      {entries.map(([key, v], i) => {
        const isOpen = open.has(key);
        const s = summary(key, v, keyed ?? false, i);
        const Chevron = isOpen ? ChevronDown : ChevronRight;
        return (
          <div key={key} className={cn("rounded-lg border border-border bg-background", isOpen && "border-l-2 border-l-primary")}>
            <div className="flex items-center gap-1 pr-1">
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => toggle(key)}
                className="flex min-h-10 min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-2 text-left outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <Chevron className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="break-words text-[13px] font-medium">{s.title}</span>
                  {s.meta && !isOpen && <span className="break-words text-xs text-muted-foreground">{s.meta}</span>}
                </span>
                {s.trailing && <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">{s.trailing}</span>}
              </button>
              <Button variant="ghost" size="icon-xs" aria-label={`Remove ${s.title}`} onClick={() => onChange(entries.filter(([k]) => k !== key))}>
                <X />
              </Button>
            </div>
            {isOpen && (
              <div className="flex flex-col gap-3 border-t border-border px-3 py-3">
                {keyed && (
                  <div className="grid gap-x-4 gap-y-1 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)] sm:items-center">
                    <span className="text-[13px] font-medium">Name</span>
                    <Input value={key} onChange={(e) => rename(key, e.target.value)} aria-label="Entry name" />
                  </div>
                )}
                <Control ctx={ctx} hp={[...hp, "*"]} value={v} onChange={(x) => onChange(entries.map(([k, y]) => (k === key ? [k, x] : [k, y])))} siblings={siblings} />
              </div>
            )}
          </div>
        );
      })}
      {(template !== undefined || entries.length > 0) && (
        <div>
          <Button variant="secondary" size="sm" onClick={add}>
            <Plus data-icon="inline-start" /> Add {singular}
          </Button>
        </div>
      )}
    </div>
  );
}

/** What the closed card says about an entry. */
function summary(key: string, v: Json, keyed: boolean, index: number): { title: string; meta: string | null; trailing: React.ReactNode } {
  if (!isObj(v)) return { title: keyed ? key : String(v), meta: null, trailing: null };
  const name = str(v.name);
  const title = keyed ? (/^[1-5]$/.test(key) ? `P${key}` : key) : name ?? str(v.about) ?? (typeof v.to === "number" ? `Raise to P${v.to}` : `#${index + 1}`);
  const parts: string[] = [];
  const about = str(v.about) ?? str(v.breaks) ?? str(v.version);
  if (about && about !== title) parts.push(about);
  for (const [k, x] of Object.entries(v)) {
    if (Array.isArray(x) && x.length && !["match"].includes(k)) parts.push(`${x.length} ${humanize(k).toLowerCase()}`);
  }
  if (Array.isArray(v.match)) parts.push(`${v.match.length} ${v.match.length === 1 ? "pattern" : "patterns"}`);
  let trailing: React.ReactNode = null;
  if (typeof v.priority === "number") trailing = <PriorityChip priority={v.priority} />;
  else if (isObj(v.priority)) {
    trailing = (
      <>
        <PriorityChip priority={v.priority.single as number} /> one
        <PriorityChip priority={v.priority.wide as number} /> many
      </>
    );
  } else if (typeof v.to === "number") trailing = <PriorityChip priority={v.to} />;
  else if (str(v.criticality)) trailing = humanize(v.criticality as string);
  else if (typeof v.tier === "number") trailing = `Tier ${v.tier}`;
  return { title, meta: parts.join(" · ") || null, trailing };
}

/** Text, number or yes/no. Long or multi-line text gets a textarea. */
function ScalarInput({ value, onChange, hint }: { value: Json; onChange: (v: Json) => void; hint: Hint }) {
  if (typeof value === "boolean") {
    return (
      <label className="inline-flex h-8 items-center gap-2 text-[13px]">
        <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-primary" />
        {value ? "Yes" : "No"}
      </label>
    );
  }
  if (typeof value === "number") {
    return (
      <Input
        type="number"
        step="any"
        inputMode="decimal"
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (e.target.value !== "" && !Number.isNaN(n)) onChange(n);
        }}
        className="w-28"
      />
    );
  }
  const s = value === null ? "" : String(value);
  if (hint.multiline || s.includes("\n") || s.length > 80) {
    const rows = Math.min(16, Math.max(3, s.split("\n").length + 1));
    return <Textarea rows={rows} value={s} onChange={(e) => onChange(e.target.value)} spellCheck={false} className="whitespace-pre-wrap break-words text-[13px]" />;
  }
  return <Input value={s} onChange={(e) => onChange(e.target.value)} className={cn(looksLikePattern(s) && "font-mono text-xs")} />;
}

/** A list of words or patterns as chips. Click one to edit it; Enter in the box at the end adds another. */
function ChipList({ items, onChange }: { items: Json[]; onChange: (v: Json) => void }) {
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const numeric = items.length > 0 && items.every((x) => typeof x === "number");
  const parse = (s: string): Json => (numeric && s.trim() !== "" && !Number.isNaN(Number(s)) ? Number(s) : s);

  const commit = (i: number, s: string) => {
    const next = s.trim() === "" ? items.filter((_, j) => j !== i) : items.map((x, j) => (j === i ? parse(s) : x));
    onChange(next);
    setEditing(null);
  };
  const add = () => {
    if (draft.trim() === "") return;
    onChange([...items, parse(draft)]);
    setDraft("");
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {items.map((x, i) => {
        const s = String(x);
        if (editing === i) {
          return (
            <Input
              key={i}
              autoFocus
              defaultValue={s}
              aria-label="Edit entry"
              onBlur={(e) => commit(i, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") commit(i, e.currentTarget.value);
                if (e.key === "Escape") setEditing(null);
              }}
              className="h-7 w-auto min-w-40 max-w-full font-mono text-xs"
            />
          );
        }
        return (
          <Badge key={i} variant="outline" className="h-auto max-w-full gap-0 rounded-md py-0.5 pr-0.5 pl-2 whitespace-normal">
            <button type="button" onClick={() => setEditing(i)} className={cn("break-all text-left outline-none focus-visible:underline", looksLikePattern(s) ? "font-mono" : "")} title="Edit">
              {s}
            </button>
            <button type="button" aria-label={`Remove ${s}`} onClick={() => commit(i, "")} className="ml-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
              <X className="size-3" aria-hidden="true" />
            </button>
          </Badge>
        );
      })}
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
        placeholder={items.length ? "Add another…" : "Add…"}
        aria-label="Add an entry"
        className="h-7 w-44 font-mono text-xs"
      />
    </div>
  );
}
