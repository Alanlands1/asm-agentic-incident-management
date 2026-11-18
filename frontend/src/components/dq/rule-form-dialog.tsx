"use client";

import { useState, useEffect } from "react";
import { DQRule, DQRuleCreateInput, DQRuleUpdateInput, DQOperator, ApplyToScope } from "@/types/dq";
import { dqService } from "@/services/dq-service";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

interface RuleFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ruleToEdit?: DQRule | null;
  onSubmit: (data: DQRuleCreateInput | DQRuleUpdateInput) => Promise<void>;
}

const OPERATORS: { label: string; value: DQOperator; needsValue: boolean }[] = [
  { label: "Equals", value: "equals", needsValue: true },
  { label: "Not equals", value: "not_equals", needsValue: true },
  { label: "Contains", value: "contains", needsValue: true },
  { label: "Not contains", value: "not_contains", needsValue: true },
  { label: "Starts with", value: "starts_with", needsValue: true },
  { label: "Regex match", value: "regex", needsValue: true },
  { label: "Is empty", value: "is_empty", needsValue: false },
  { label: "Is not empty", value: "is_not_empty", needsValue: false },
  { label: "Length less than", value: "length_lt", needsValue: true },
  { label: "Length greater than", value: "length_gt", needsValue: true },
];

const FIELDS = [
  "short_description",
  "description",
  "caller",
  "service",
  "priority",
  "assignment_group",
  "resolution_notes",
];

export function RuleFormDialog({
  open,
  onOpenChange,
  ruleToEdit,
  onSubmit,
}: RuleFormDialogProps) {
  const [name, setName] = useState(ruleToEdit?.name || "");
  const [description, setDescription] = useState(ruleToEdit?.description || "");
  const [field, setField] = useState(ruleToEdit?.field || "short_description");
  const [operator, setOperator] = useState<DQOperator>(ruleToEdit?.operator || "is_empty");
  const [value, setValue] = useState(ruleToEdit?.value || "");
  const [applyTo, setApplyTo] = useState<ApplyToScope>(ruleToEdit?.apply_to || "both");
  const [source, setSource] = useState(ruleToEdit?.source || "");
  const [service, setService] = useState(ruleToEdit?.service || "");
  const [sourcesList, setSourcesList] = useState<{ code: string; name: string }[]>([
    { code: "servicenow", name: "ServiceNow" },
    { code: "jira", name: "Jira" },
    { code: "mailbox", name: "Support Mailbox" },
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    dqService
      .getSources()
      .then((items) => {
        if (active && items?.length) {
          setSourcesList(items.map((i) => ({ code: i.code, name: i.name })));
        }
      })
      .catch(() => {
        // Fallback already pre-set to standard sources
      });
    return () => {
      active = false;
    };
  }, []);

  const selectedOp = OPERATORS.find((o) => o.value === operator);
  const needsValue = selectedOp?.needsValue ?? true;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!name.trim()) {
      setFormError("Rule name is required");
      return;
    }

    if (needsValue && !value.trim()) {
      setFormError(`Value is required for operator "${operator}"`);
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit({
        name: name.trim(),
        description: description.trim() ? description.trim() : null,
        field,
        operator,
        value: needsValue ? value.trim() : null,
        apply_to: applyTo,
        source: source.trim() ? source.trim() : null,
        service: service.trim() ? service.trim() : null,
      });
      onOpenChange(false);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to save rule");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">
              {ruleToEdit ? "Edit data quality rule" : "New data quality rule"}
            </DialogTitle>
            <p className="text-muted-foreground">
              Define deterministic quality checks, field matching operators, and evaluation scopes.
            </p>
          </DialogHeader>

          {formError && (
            <Alert variant="destructive">
              <AlertDescription>{formError}</AlertDescription>
            </Alert>
          )}

          <div className="flex flex-col gap-4">
            {/* Rule Name */}
            <div>
              <label className="mb-1.5 block text-xs font-medium">Rule name *</label>
              <Input
                placeholder="e.g. Missing short description"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>

            {/* Rule Description */}
            <div>
              <label className="mb-1.5 block text-xs font-medium">Description (optional)</label>
              <Input
                placeholder="e.g. Flags tickets where summary does not meet minimum quality criteria"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              <span className="mt-1 block text-xs text-muted-foreground">
                Detailed business context or defect rationale for operations.
              </span>
            </div>

            {/* Target Field & Operator */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium">Field *</label>
                <select
                  value={field}
                  onChange={(e) => setField(e.target.value)}
                  className={selectClass}
                >
                  {FIELDS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-xs text-muted-foreground">
                  Ticket column to validate.
                </span>
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium">Operator *</label>
                <select
                  value={operator}
                  onChange={(e) => setOperator(e.target.value as DQOperator)}
                  className={selectClass}
                >
                  {OPERATORS.map((op) => (
                    <option key={op.value} value={op.value}>
                      {op.label}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-xs text-muted-foreground">
                  Deterministic check logic.
                </span>
              </div>
            </div>

            {/* Value if operator needs value */}
            {needsValue && (
              <div>
                <label className="mb-1.5 block text-xs font-medium">Value *</label>
                <Input
                  placeholder={
                    operator.startsWith("length_") ? "e.g. 10 (characters)" : "e.g. test or pattern"
                  }
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
              </div>
            )}

            {/* Lifecycle Scope */}
            <div>
              <label className="mb-1.5 block text-xs font-medium">Applies to</label>
              <select
                value={applyTo}
                onChange={(e) => setApplyTo(e.target.value as ApplyToScope)}
                className={selectClass}
              >
                <option value="both">Stored and incoming tickets</option>
                <option value="existing">Stored tickets only</option>
                <option value="new">Incoming tickets only</option>
              </select>
            </div>

            {/* Apply To Source & Service */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium">Source</label>
                <select
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  className={selectClass}
                >
                  <option value="">All sources</option>
                  {sourcesList.map((s) => (
                    <option key={s.code} value={s.code}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-xs text-muted-foreground">
                  Leave as All sources to run across every feed, or select a source.
                </span>
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium">Service (optional)</label>
                <Input
                  placeholder="e.g. PayrollPro"
                  value={service}
                  onChange={(e) => setService(e.target.value)}
                />
                <span className="mt-1 block text-xs text-muted-foreground">
                  Leave empty for all application services.
                </span>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={submitting}
            >
              {submitting ? "Saving…" : ruleToEdit ? "Update rule" : "Create rule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
