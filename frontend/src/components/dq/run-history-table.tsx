"use client";

import { useState } from "react";
import { DQRun, DQRunDetail } from "@/types/dq";
import { Card } from "@/components/ui/card";
import { ListRow } from "@/components/console/list-row";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CircleCheck, CircleX, RotateCcw, Eye } from "lucide-react";

interface RunHistoryTableProps {
  runs: DQRun[];
  loading: boolean;
  onRevert: (id: number) => Promise<unknown>;
  onInspect: (id: number) => Promise<DQRunDetail>;
}

export function RunHistoryTable({
  runs,
  loading,
  onRevert,
  onInspect,
}: RunHistoryTableProps) {
  const [selectedRunDetail, setSelectedRunDetail] = useState<DQRunDetail | null>(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [inspectingId, setInspectingId] = useState<number | null>(null);
  const [revertingId, setRevertingId] = useState<number | null>(null);

  const handleOpenDetail = async (id: number) => {
    setInspectingId(id);
    try {
      const detail = await onInspect(id);
      setSelectedRunDetail(detail);
      setDetailModalOpen(true);
    } catch {
      alert("Failed to load run details");
    } finally {
      setInspectingId(null);
    }
  };

  const handleRevert = async (id: number) => {
    if (!confirm(`Revert DQ Run #${id}? All tickets flagged exclusively by this run will be unflagged.`)) {
      return;
    }
    setRevertingId(id);
    try {
      await onRevert(id);
    } catch {
      alert("Failed to revert run");
    } finally {
      setRevertingId(null);
    }
  };

  if (loading && runs.length === 0) {
    return <Card className="px-4 py-8 text-center text-muted-foreground">Loading execution runs…</Card>;
  }

  if (runs.length === 0) {
    return (
      <Card className="border-dashed px-4 py-8 text-center text-muted-foreground">
        No DQ runs yet. Trigger a run above to test the enabled rules.
      </Card>
    );
  }

  return (
    <>
      <Card className="gap-0 py-0">
        <ul role="list">
          {runs.map((run) => (
            <ListRow
              key={run.id}
              itemKey={`#${run.id}`}
              title={<span className="capitalize">{run.trigger} run · {run.scope}</span>}
              meta={
                <>
                  <span className="font-mono">{new Date(run.started_at).toLocaleString()}</span>
                  <span aria-hidden="true">·</span>
                  <span className="tabular-nums">
                    <span className={run.tickets_flagged ? "font-medium text-foreground" : undefined}>
                      {run.tickets_flagged ?? 0}
                    </span>{" "}
                    flagged of {run.tickets_evaluated ?? 0} checked
                  </span>
                </>
              }
              trailing={
                <span className="inline-flex items-center gap-1.5 capitalize text-foreground">
                  {run.status === "completed" ? (
                    <CircleCheck className="size-4" aria-hidden="true" />
                  ) : run.status === "reverted" ? (
                    <RotateCcw className="size-4" aria-hidden="true" />
                  ) : (
                    <CircleX className="size-4" aria-hidden="true" />
                  )}
                  {run.status}
                </span>
              }
              actions={
                <div className="flex gap-1 max-sm:[&>*]:h-11 max-sm:[&>*]:flex-1">
                  <Button
                    size="icon"
                    variant="ghost"
                    title="View matches"
                    aria-label={`View matches for run ${run.id}`}
                    disabled={inspectingId === run.id}
                    onClick={() => handleOpenDetail(run.id)}
                  >
                    <Eye />
                  </Button>
                  {run.status === "completed" && (
                    <Button
                      size="icon"
                      variant="ghost"
                      title="Revert run"
                      aria-label={`Revert run ${run.id}`}
                      disabled={revertingId === run.id}
                      onClick={() => handleRevert(run.id)}
                    >
                      <RotateCcw />
                    </Button>
                  )}
                </div>
              }
            />
          ))}
        </ul>
      </Card>

      {/* Inspect matches modal */}
      <Dialog open={detailModalOpen} onOpenChange={setDetailModalOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Run #{selectedRunDetail?.id} flagged tickets</DialogTitle>
          </DialogHeader>

          {selectedRunDetail?.matches?.length === 0 ? (
            <div className="p-6 text-center text-muted-foreground">
              No tickets were flagged in this run.
            </div>
          ) : (
            <ul role="list" className="rounded-lg border border-border">
              {selectedRunDetail?.matches?.map((m) => (
                <ListRow
                  key={m.ticket_id}
                  itemKey={m.ticket_id}
                  title={m.ticket_short_description || "—"}
                  meta={[
                    `${m.rule_name} (rule #${m.rule_id})`,
                    m.ticket_service || "No service",
                    m.ticket_priority || "No priority",
                  ].join(" · ")}
                />
              ))}
            </ul>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
