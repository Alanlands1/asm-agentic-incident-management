"use client";

import Link from "next/link";
import { AgentWorkflowLayout } from "@/components/layout/agent-workflow-layout";
import { PageHeader } from "@/components/console/page-header";
import { StatTile } from "@/components/console/stat-tile";
import { useDQRuns } from "@/hooks/use-dq-runs";
import { useDQRules } from "@/hooks/use-dq-rules";
import { RunPipelineCard } from "@/components/dq/run-pipeline-card";
import { RunHistoryTable } from "@/components/dq/run-history-table";
import { Button } from "@/components/ui/button";
import { ArrowRight, RefreshCw, SlidersHorizontal } from "lucide-react";

export default function ExecuteDQRulesPage() {
  const {
    runs,
    loading: runsLoading,
    fetchRuns,
    triggerRun,
    revertRun,
    getRunDetail,
  } = useDQRuns();

  const { rules } = useDQRules();

  const handleExecuteRun = async (input: Parameters<typeof triggerRun>[0]) => {
    await triggerRun(input);
  };

  return (
    <AgentWorkflowLayout currentStep={1}>
      <PageHeader
        title="Data quality runs"
        context="Run the enabled rules against ServiceNow tickets, inspect what each run flagged and revert a run in one step."
        actions={
          <>
            <Button variant="secondary" onClick={fetchRuns} disabled={runsLoading}>
              <RefreshCw className={runsLoading ? "animate-spin" : ""} />
              Refresh runs
            </Button>
            <Button variant="secondary" render={<Link href="/dq-rules" />} nativeButton={false}>
              <SlidersHorizontal />
              Manage rules ({rules.length})
            </Button>
          </>
        }
      />

      <RunPipelineCard onRun={handleExecuteRun} />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 [&>*:first-child]:col-span-2 md:[&>*:first-child]:col-span-1">
        <StatTile variant="primary" label="Runs" value={runs.length} window="Logged with execution snapshots" />
        <StatTile
          label="Active rules applied"
          value={rules.filter((r) => r.is_enabled).length}
          window={`of ${rules.length} configured`}
        />
        <StatTile label="Rollback" value="One-step revert" window="Restores pre-run ticket flags" />
      </div>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <h2 className="text-sm font-semibold">Run history</h2>
            <p className="text-xs text-muted-foreground">
              Every manual and automated run, with ticket counts and revert.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground tabular-nums">
              {runs.length} {runs.length === 1 ? "run" : "runs"}
            </span>
            <Button variant="secondary" size="sm" render={<Link href="/tickets" />} nativeButton={false}>
              Browse tickets
              <ArrowRight />
            </Button>
          </div>
        </div>

        <RunHistoryTable
          runs={runs}
          loading={runsLoading}
          onRevert={revertRun}
          onInspect={getRunDetail}
        />
      </section>
    </AgentWorkflowLayout>
  );
}
