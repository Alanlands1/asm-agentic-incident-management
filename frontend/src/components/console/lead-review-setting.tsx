"use client";

import { useEffect, useState } from "react";
import { SectionHead } from "@/components/console/sync-parts";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { usePerson } from "@/lib/view-as";
import { adminService } from "@/services/admin-service";

type Mode = "always" | "p1_p2" | "never";
const MODES: { value: Mode; label: string; says: string }[] = [
  { value: "always", label: "Always", says: "A lead approves every closure note before it is sent." },
  { value: "p1_p2", label: "Only P1–P2", says: "A lead approves closure notes for P1 and P2 tickets; the engineer sends all others." },
  { value: "never", label: "Never", says: "The engineer sends every closure note without lead approval." },
];

/** Lead review before close (design D3), saved as the LEAD_REVIEW setting through the admin API. */
export function LeadReviewSetting() {
  const person = usePerson();
  const [mode, setMode] = useState<Mode | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminService.listSettings().then(
      (all) => setMode((all.find((s) => s.key === "LEAD_REVIEW")?.value as Mode | undefined) ?? "p1_p2"),
      (e: unknown) => setError(e instanceof Error ? e.message : "Couldn't load the setting. Try again.")
    );
  }, []);

  const choose = (value: Mode) => {
    setSaving(true);
    setError(null);
    adminService
      .putSetting("LEAD_REVIEW", value, person)
      .then((s) => setMode(s.value as Mode))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Couldn't save the setting. Try again."))
      .finally(() => setSaving(false));
  };

  return (
    <Card className="gap-0 py-0">
      <SectionHead title="Lead approval before closure" />
      <div className="flex flex-col gap-3 px-4 py-4">
        <p className="text-muted-foreground">
          Whether a lead approves the closure note before it goes to Jira. The engineer submits it; the lead approves it or sends it back with what to change.
        </p>
        <div role="group" aria-label="Lead review before close" className="flex flex-wrap gap-2">
          {MODES.map((m) => (
            <Button key={m.value} size="sm" variant={mode === m.value ? "default" : "secondary"} aria-pressed={mode === m.value} disabled={saving || mode === null} onClick={() => choose(m.value)}>
              {m.label}
            </Button>
          ))}
        </div>
        {mode && <p className="text-xs text-muted-foreground">{MODES.find((m) => m.value === mode)?.says} Applies at once, to tickets not yet sent.</p>}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
      </div>
    </Card>
  );
}
