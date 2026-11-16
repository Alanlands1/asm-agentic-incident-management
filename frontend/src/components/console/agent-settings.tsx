"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { SectionHead } from "@/components/console/sync-parts";
import { usePerson } from "@/lib/view-as";
import { adminService } from "@/services/admin-service";
import { AdminSetting, SettingValue } from "@/types/admin";

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

const MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"];
const EFFORTS: [string, string][] = [
  ["low", "Low: quick checks"],
  ["medium", "Medium"],
  ["high", "High: thinks harder"],
  ["xhigh", "Extra high"],
  ["max", "Maximum: slowest"],
];

type Settings = Record<string, AdminSetting>;

function Row({ label, hint, children, note }: { label: string; hint?: string; children: React.ReactNode; note?: React.ReactNode }) {
  return (
    <div className="grid gap-x-4 gap-y-1.5 border-b border-border px-4 py-3 last:border-b-0 md:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
      <div>
        <p className="text-[13px] font-medium">{label}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        {children}
        {note}
      </div>
    </div>
  );
}

/** One agent's model, effort and failure cut-off, plus the model settings every agent shares. Saves each change on its own. */
export function AgentSettings({ prefix, breakerKey }: { prefix: "DQ" | "TRIAGE"; breakerKey: string }) {
  const person = usePerson();
  const [s, setS] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [breaker, setBreaker] = useState("");

  useEffect(() => {
    adminService
      .listSettings()
      .then((rows) => {
        const map = Object.fromEntries(rows.map((r) => [r.key, r]));
        setS(map);
        setBreaker(String(map[breakerKey]?.value ?? ""));
      })
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : "Couldn't load settings"));
  }, [breakerKey]);

  const apply = async (key: string, value: SettingValue | undefined) => {
    setNotes((n) => ({ ...n, [key]: { ok: true, text: "Saving…" } }));
    try {
      const row = value === undefined ? await adminService.resetSetting(key, person) : await adminService.putSetting(key, value, person);
      setS((cur) => (cur ? { ...cur, [key]: row } : cur));
      setNotes((n) => ({ ...n, [key]: { ok: true, text: "Saved" } }));
    } catch (e) {
      setNotes((n) => ({ ...n, [key]: { ok: false, text: e instanceof Error ? e.message : "Couldn't save" } }));
    }
  };

  const note = (key: string) =>
    notes[key] && <p className={notes[key].ok ? "text-xs text-muted-foreground" : "text-xs font-medium text-destructive"}>{notes[key].text}</p>;

  if (loadError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{loadError}</AlertDescription>
      </Alert>
    );
  }
  if (!s) return <Card className="px-4 py-6 text-muted-foreground">Loading settings…</Card>;

  const modelKey = `${prefix}_LLM_MODEL`;
  const effortKey = `${prefix}_LLM_EFFORT`;
  const model = (s[modelKey]?.value as string | null) ?? "";
  const effort = (s[effortKey]?.value as string | null) ?? "";
  const models = model && !MODELS.includes(model) ? [...MODELS, model] : MODELS;
  const id = (k: string) => `setting-${k}`;

  return (
    <>
      <Card className="gap-0 py-0">
        <SectionHead title="This agent" />
        <Row label="Model" hint="Which Claude model this agent calls">
          <select
            id={id(modelKey)}
            aria-label="Model"
            className={selectClass}
            value={model}
            onChange={(e) => apply(modelKey, e.target.value || undefined)}
          >
            <option value="">Use the shared model ({String(s.LLM_MODEL?.value)})</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          {note(modelKey)}
        </Row>
        <Row label="Effort" hint="How hard the model thinks. Higher is slower and costs more.">
          <select
            id={id(effortKey)}
            aria-label="Effort"
            className={selectClass}
            value={effort}
            onChange={(e) => apply(effortKey, e.target.value || undefined)}
          >
            <option value="">Use the shared effort ({String(s.LLM_EFFORT?.value)})</option>
            {EFFORTS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
          {note(effortKey)}
        </Row>
        <Row label="Stop after failures" hint="Model failures in a row before a run stops calling the model">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              apply(breakerKey, Number(breaker));
            }}
          >
            <Input
              type="number"
              min={1}
              aria-label="Failures in a row"
              value={breaker}
              onChange={(e) => setBreaker(e.target.value)}
              className="max-w-28"
            />
            <Button type="submit" variant="secondary" disabled={!breaker || breaker === String(s[breakerKey]?.value)}>
              Save
            </Button>
          </form>
          {note(breakerKey)}
        </Row>
      </Card>

      <Card className="gap-0 py-0">
        <SectionHead title="Model access">
          <span className="text-xs text-muted-foreground">These apply to every agent</span>
        </SectionHead>
        <Row label="Model calls" hint="Off: agents use their rules only">
          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={Boolean(s.LLM_ENABLED?.value)}
              onChange={(e) => apply("LLM_ENABLED", e.target.checked)}
            />
            Model calls on for every agent
          </label>
          {note("LLM_ENABLED")}
        </Row>
        <Row label="Provider and limits">
          <p className="text-[13px]">
            {String(s.LLM_PROVIDER?.value)} · timeout {String(s.LLM_TIMEOUT_S?.value)} s · {String(s.LLM_TRANSPORT_RETRIES?.value)} retries
          </p>
        </Row>
      </Card>
    </>
  );
}
