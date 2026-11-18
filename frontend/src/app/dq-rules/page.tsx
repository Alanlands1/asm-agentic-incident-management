"use client";

import { useState } from "react";
import Link from "next/link";
import { AgentWorkflowLayout } from "@/components/layout/agent-workflow-layout";
import { PageHeader } from "@/components/console/page-header";
import { StatTile } from "@/components/console/stat-tile";
import { useDQRules } from "@/hooks/use-dq-rules";
import { RuleListTable } from "@/components/dq/rule-list-table";
import { RuleFormDialog } from "@/components/dq/rule-form-dialog";
import { DQRule, DQRuleCreateInput, DQRuleUpdateInput } from "@/types/dq";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Plus, RefreshCw, AlertCircle, Play } from "lucide-react";

export default function ManageDQRulesPage() {
  const {
    rules,
    loading: rulesLoading,
    error: rulesError,
    fetchRules,
    createRule,
    updateRule,
    toggleRule,
    deleteRule,
  } = useDQRules();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<DQRule | null>(null);

  const handleOpenCreate = () => {
    setEditingRule(null);
    setDialogOpen(true);
  };

  const handleOpenEdit = (rule: DQRule) => {
    setEditingRule(rule);
    setDialogOpen(true);
  };

  const handleRuleFormSubmit = async (data: DQRuleCreateInput | DQRuleUpdateInput) => {
    if (editingRule) {
      await updateRule(editingRule.id, data as DQRuleUpdateInput);
    } else {
      await createRule(data as DQRuleCreateInput);
    }
  };

  const handleToggle = async (id: number, currentStatus: boolean) => {
    try {
      await toggleRule(id, !currentStatus);
    } catch {
      alert("Failed to toggle rule status");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteRule(id);
    } catch {
      alert("Failed to delete rule");
    }
  };

  return (
    <AgentWorkflowLayout currentStep={1}>
      <PageHeader
        title="Data quality rules"
        context="Rules check incoming ServiceNow and Jira tickets in priority order; the first match sets the flag and defect reason."
        actions={
          <>
            <Button variant="secondary" onClick={fetchRules} disabled={rulesLoading}>
              <RefreshCw className={rulesLoading ? "animate-spin" : ""} />
              Refresh
            </Button>
            <Button variant="secondary" render={<Link href="/dq-rules/execute" />} nativeButton={false}>
              <Play />
              Go to runs
            </Button>
            <Button onClick={handleOpenCreate}>
              <Plus />
              New rule
            </Button>
          </>
        }
      />

      {rulesError && (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertDescription>Unable to connect to the backend service: {rulesError}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 [&>*:first-child]:col-span-2 md:[&>*:first-child]:col-span-1">
        <StatTile
          variant="primary"
          label="Active rules"
          value={rules.filter((r) => r.is_enabled).length}
          window={`of ${rules.length} configured`}
        />
        <StatTile label="Rule precedence" value="First match wins" window="Priority order decides the flag" />
        <StatTile label="Supported operators" value="10" window="Empty, regex, length, equals, contains and more" />
      </div>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <h2 className="text-sm font-semibold">Configured rules</h2>
            <p className="text-xs text-muted-foreground">Rules evaluate in strict order.</p>
          </div>
          <span className="text-xs text-muted-foreground tabular-nums">
            {rules.length} {rules.length === 1 ? "rule" : "rules"} configured
          </span>
        </div>

        <RuleListTable
          rules={rules}
          loading={rulesLoading}
          onEdit={handleOpenEdit}
          onToggle={handleToggle}
          onDelete={handleDelete}
        />
      </section>

      <RuleFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        ruleToEdit={editingRule}
        onSubmit={handleRuleFormSubmit}
      />
    </AgentWorkflowLayout>
  );
}
