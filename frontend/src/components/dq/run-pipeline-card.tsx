"use client";

import { useState } from "react";
import { ApplyToScope, DQRunCreateInput } from "@/types/dq";
import { Card } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { AlertCircle, CircleCheck, Play } from "lucide-react";

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

interface RunPipelineCardProps {
  onRun: (input: DQRunCreateInput) => Promise<void>;
}

export function RunPipelineCard({ onRun }: RunPipelineCardProps) {
  const [scope, setScope] = useState<ApplyToScope>("existing");
  const [source, setSource] = useState<string>("servicenow");
  const [isRunning, setIsRunning] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: "success" | "error"; text: string } | null>(
    null
  );

  const handleExecute = async () => {
    setIsRunning(true);
    setStatusMsg(null);
    try {
      await onRun({
        scope,
        source: source.trim() || undefined,
        trigger: "manual",
      });
      setStatusMsg({ type: "success", text: "DQ pipeline executed successfully!" });
    } catch (err: unknown) {
      setStatusMsg({
        type: "error",
        text: err instanceof Error ? err.message : "Run failed",
      });
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <Card className="gap-0 py-0">
      <div className="flex flex-col gap-0.5 border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Run rule evaluation</h2>
        <p className="text-xs text-muted-foreground">
          Run the enabled rules against tickets for the chosen scope and source.
        </p>
      </div>
      <div className="flex flex-col gap-4 p-4">
        {statusMsg && (
          <Alert variant={statusMsg.type === "error" ? "destructive" : "default"}>
            {statusMsg.type === "error" ? <AlertCircle /> : <CircleCheck />}
            <AlertDescription>{statusMsg.text}</AlertDescription>
          </Alert>
        )}

        <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-12">
          <div className="flex flex-col gap-1.5 sm:col-span-5">
            <label htmlFor="dq-run-scope" className="text-xs font-medium">
              Evaluation scope
            </label>
            <select
              id="dq-run-scope"
              value={scope}
              onChange={(e) => setScope(e.target.value as ApplyToScope)}
              className={selectClass}
            >
              <option value="existing">Existing tickets only</option>
              <option value="both">Both (existing and ingestion stream)</option>
              <option value="new">New unprocessed only</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5 sm:col-span-4">
            <label htmlFor="dq-run-source" className="text-xs font-medium">
              Target source
            </label>
            <select
              id="dq-run-source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className={selectClass}
            >
              <option value="servicenow">ServiceNow (servicenow_tickets)</option>
              <option value="">All sources</option>
            </select>
          </div>

          <div className="sm:col-span-3">
            <Button onClick={handleExecute} disabled={isRunning} className="w-full max-sm:h-11">
              <Play />
              {isRunning ? "Evaluating…" : "Apply rules"}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
