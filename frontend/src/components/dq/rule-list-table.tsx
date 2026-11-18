"use client";

import { DQRule } from "@/types/dq";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ListRow } from "@/components/console/list-row";
import { CircleCheck, CircleOff, Edit2, Trash2, Power } from "lucide-react";

interface RuleListTableProps {
  rules: DQRule[];
  loading: boolean;
  onEdit: (rule: DQRule) => void;
  onToggle: (id: number, currentStatus: boolean) => void;
  onDelete: (id: number) => void;
}

export function RuleListTable({
  rules,
  loading,
  onEdit,
  onToggle,
  onDelete,
}: RuleListTableProps) {
  if (loading && rules.length === 0) {
    return (
      <Card className="px-4 py-8 text-center text-muted-foreground">
        Loading data quality rules…
      </Card>
    );
  }

  if (rules.length === 0) {
    return (
      <Card className="border-dashed px-4 py-8 text-center text-muted-foreground">
        No DQ rules yet. Create your first rule above to get started.
      </Card>
    );
  }

  return (
    <Card className="gap-0 py-0">
      <ul role="list">
        {rules.map((rule) => (
          <ListRow
            key={rule.id}
            itemKey={`#${rule.id}`}
            title={rule.name}
            meta={
              <>
                {rule.description && <span className="w-full text-body">{rule.description}</span>}
                <span className="font-mono">
                  {rule.field} {rule.operator}
                  {rule.value !== null && rule.value !== undefined && <> &quot;{rule.value}&quot;</>}
                </span>
                <span aria-hidden="true">·</span>
                <span className="capitalize">{rule.apply_to}</span>
                <span aria-hidden="true">·</span>
                <span>{rule.source || "Global (all sources)"}</span>
                {rule.service && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="font-mono">svc: {rule.service}</span>
                  </>
                )}
              </>
            }
            trailing={
              rule.is_enabled ? (
                <span className="inline-flex items-center gap-1.5 text-foreground">
                  <CircleCheck className="size-4" aria-hidden="true" />
                  Active
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5">
                  <CircleOff className="size-4" aria-hidden="true" />
                  Disabled
                </span>
              )
            }
            actions={
              <div className="flex gap-1 max-sm:[&>*]:h-11 max-sm:[&>*]:flex-1">
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => onToggle(rule.id, rule.is_enabled)}
                  title={rule.is_enabled ? "Disable rule" : "Enable rule"}
                  aria-label={`${rule.is_enabled ? "Disable" : "Enable"} rule ${rule.name}`}
                >
                  <Power />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => onEdit(rule)}
                  title="Edit rule"
                  aria-label={`Edit rule ${rule.name}`}
                >
                  <Edit2 />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => {
                    if (confirm(`Delete rule "${rule.name}"?`)) {
                      onDelete(rule.id);
                    }
                  }}
                  title="Delete rule"
                  aria-label={`Delete rule ${rule.name}`}
                >
                  <Trash2 />
                </Button>
              </div>
            }
          />
        ))}
      </ul>
    </Card>
  );
}
