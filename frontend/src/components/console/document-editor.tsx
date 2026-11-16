"use client";

import { useEffect, useId, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsIndicator, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SectionHead } from "@/components/console/sync-parts";
import { DocumentBlocks } from "@/components/console/document-blocks";
import { usePerson } from "@/lib/view-as";
import { adminService } from "@/services/admin-service";
import { Json } from "@/types/admin";

type Mode = "blocks" | "yaml";

/** A rule or reference file, as editable blocks or as YAML text. The backend checks every save before anything changes. */
export function DocumentEditor({ name, label, note }: { name: string; label: string; note?: string }) {
  const person = usePerson();
  const id = useId();
  const [mode, setMode] = useState<Mode>("blocks");
  // Blocks mode holds the parsed document; YAML mode holds the text. `saved` is the serialised last-saved value.
  const [value, setValue] = useState<Json | null>(null);
  const [saved, setSaved] = useState("");
  const [overridden, setOverridden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);

  const serialise = (v: Json) => (mode === "yaml" ? String(v) : JSON.stringify(v));

  const switchMode = (m: Mode) => {
    setMode(m);
    setValue(null);
    setError(null);
  };

  const load = (m: Mode) => {
    const req =
      m === "yaml"
        ? adminService.getYaml(name).then((d) => ({ value: d.text as Json, overridden: d.overridden }))
        : adminService.getDocument(name).then((d) => ({ value: d.document, overridden: d.overridden }));
    return req
      .then((d) => {
        setValue(d.value);
        setSaved(m === "yaml" ? String(d.value) : JSON.stringify(d.value));
        setOverridden(d.overridden);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : `Couldn't load ${label}`));
  };

  useEffect(() => {
    load(mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, mode]);

  const save = async () => {
    if (value === null) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      if (mode === "yaml") {
        const d = await adminService.putYaml(name, String(value), person);
        setValue(d.text);
        setSaved(d.text);
        setOverridden(d.overridden);
      } else {
        const d = await adminService.putDocument(name, value, person);
        setValue(d.document);
        setSaved(JSON.stringify(d.document));
        setOverridden(d.overridden);
      }
      setStatus("Saved. The agents use it from their next ticket.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    setError(null);
    try {
      await adminService.resetDocument(name, person);
      setConfirm(false);
      await load(mode);
      setStatus("Back to the repo file.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't reset");
    } finally {
      setBusy(false);
    }
  };

  const dirty = value !== null && serialise(value) !== saved;
  const edit = (v: Json) => {
    setValue(v);
    setStatus(null);
  };

  return (
    <Card className="gap-0 py-0">
      <SectionHead title={label}>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground">{overridden ? "Changed by an admin" : "Using the repo file"}</span>
          <Tabs value={mode} onValueChange={(v) => switchMode(v as Mode)}>
            <TabsList variant="pill" aria-label="How to edit">
              <TabsTrigger value="blocks" disabled={dirty && mode !== "blocks"} title={dirty ? "Save or discard your changes first" : undefined}>
                Blocks
              </TabsTrigger>
              <TabsTrigger value="yaml" disabled={dirty && mode !== "yaml"} title={dirty ? "Save or discard your changes first" : undefined}>
                YAML
              </TabsTrigger>
              <TabsIndicator />
            </TabsList>
          </Tabs>
        </div>
      </SectionHead>
      <div className="flex flex-col gap-3 px-4 py-3">
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
        {value === null ? (
          !error && <p className="text-muted-foreground">Loading…</p>
        ) : mode === "yaml" ? (
          <>
            <label htmlFor={id} className="sr-only">
              {label} (YAML)
            </label>
            <Textarea
              id={id}
              rows={22}
              spellCheck={false}
              value={String(value)}
              onChange={(e) => edit(e.target.value)}
              className="whitespace-pre-wrap break-words font-mono text-xs"
            />
          </>
        ) : (
          <DocumentBlocks doc={name} value={value} onChange={edit} />
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription className="whitespace-pre-wrap break-words">{error}</AlertDescription>
          </Alert>
        )}
        {status && <p className="text-xs text-muted-foreground">{status}</p>}
        {value !== null && (
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={save} disabled={!dirty || busy}>
              {busy ? "Saving…" : "Save"}
            </Button>
            {dirty && (
              <Button variant="ghost" onClick={() => edit(mode === "yaml" ? saved : (JSON.parse(saved) as Json))} disabled={busy}>
                Discard changes
              </Button>
            )}
            {overridden && (
              <Dialog open={confirm} onOpenChange={setConfirm}>
                <Button variant="secondary" onClick={() => setConfirm(true)} disabled={busy}>
                  Reset to the repo file
                </Button>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Reset {label}?</DialogTitle>
                    <DialogDescription>
                      The admin version is replaced by the file in the repo. The change history keeps the admin version.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <DialogClose render={<Button variant="secondary" />}>Cancel</DialogClose>
                    <Button onClick={reset} disabled={busy}>
                      Reset
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            )}
            <span className="text-xs text-muted-foreground">Comments in the repo file are not kept after the first save.</span>
          </div>
        )}
      </div>
    </Card>
  );
}
