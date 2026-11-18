"use client";

import { useState } from "react";
import { AgentWorkflowLayout } from "@/components/layout/agent-workflow-layout";
import { PageHeader } from "@/components/console/page-header";
import { StatTile } from "@/components/console/stat-tile";
import { ListRow } from "@/components/console/list-row";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowRight, Scale, Clock, CircleCheck } from "lucide-react";

interface PriorityRule {
  id: string;
  condition: string;
  reported: string;
  normalized: string;
  impactTier: string;
  rationale: string;
  status: "Active" | "Enforced";
}

const TRIAGE_RULES: PriorityRule[] = [
  {
    id: "TR-001",
    condition: "Avatar / Profile photo / UI theme preference bug",
    reported: "1 - Critical",
    normalized: "5 - Planning",
    impactTier: "Tier 4 (Cosmetic)",
    rationale: "Cosmetic presentation issue with zero business transaction disruption.",
    status: "Enforced",
  },
  {
    id: "TR-002",
    condition: "SalesConnect CRM opportunity locked during quarter-end",
    reported: "3 - Moderate",
    normalized: "2 - High",
    impactTier: "Tier 1 (Revenue)",
    rationale: "Quarter-end policy triggers automatic +1 priority escalation for opportunity updates.",
    status: "Enforced",
  },
  {
    id: "TR-003",
    condition: "BillingEngine payment gateway / settlement timeout",
    reported: "2 - High",
    normalized: "1 - Critical",
    impactTier: "Tier 1 (Core Financials)",
    rationale: "Core transactional failure affecting active payment settlement pipeline.",
    status: "Enforced",
  },
  {
    id: "TR-004",
    condition: "Single user Active Directory / SSO lockout",
    reported: "1 - Critical",
    normalized: "4 - Low",
    impactTier: "Tier 3 (Isolated)",
    rationale: "Isolated individual impact with self-service unlock runbook available.",
    status: "Enforced",
  },
  {
    id: "TR-005",
    condition: "Complete SSO Gateway / Okta authentication outage",
    reported: "2 - High",
    normalized: "1 - Critical",
    impactTier: "Tier 1 (Enterprise Wide)",
    rationale: "Multi-tenant authentication barrier blocking all staff logins.",
    status: "Enforced",
  },
];

const SLA_MATRIX = [
  { priority: "P1 - Critical", targetResponse: "15 mins", targetResolution: "4 hours" },
  { priority: "P2 - High", targetResponse: "30 mins", targetResolution: "8 hours" },
  { priority: "P3 - Moderate", targetResponse: "2 hours", targetResolution: "24 hours" },
  { priority: "P4 - Low", targetResponse: "4 hours", targetResolution: "72 hours" },
  { priority: "P5 - Planning", targetResponse: "24 hours", targetResolution: "Next Sprint" },
];

const SELECT_CLASS =
  "h-8 w-full rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none transition-colors duration-[80ms] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** Priority chip for a level 1-5. P5 has no chip of its own, so it shares the quiet P4 style. */
function PriorityChip({ level }: { level: number }) {
  const variant = `p${Math.min(level, 4)}` as "p1" | "p2" | "p3" | "p4";
  return <Badge variant={variant}>P{level}</Badge>;
}

/** "1 - Critical" -> 1 */
const levelOf = (priority: string) => Number(priority.match(/\d/)?.[0] ?? 0);

function PriorityChange({ from, to }: { from: string; to: string }) {
  return (
    <span
      role="img"
      aria-label={`Reported P${levelOf(from)}, normalized to P${levelOf(to)}`}
      className="inline-flex items-center gap-1"
    >
      <PriorityChip level={levelOf(from)} />
      <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
      <PriorityChip level={levelOf(to)} />
    </span>
  );
}

const promotedCount = TRIAGE_RULES.filter((r) => levelOf(r.normalized) < levelOf(r.reported)).length;
const demotedCount = TRIAGE_RULES.filter((r) => levelOf(r.normalized) > levelOf(r.reported)).length;

export default function TriagePage() {
  const [selectedApp, setSelectedApp] = useState("SalesConnect CRM");
  const [reportedPriority, setReportedPriority] = useState("1 - Critical");
  const [ticketSummary, setTicketSummary] = useState("User profile photo failed to sync in customer dashboard");
  const [simulatedResult, setSimulatedResult] = useState<{
    normalized: string;
    action: string;
    justification: string;
    sla: string;
  } | null>(null);

  const handleSimulateTriage = () => {
    const lower = ticketSummary.toLowerCase();
    if (lower.includes("photo") || lower.includes("avatar") || lower.includes("theme") || lower.includes("color")) {
      setSimulatedResult({
        normalized: "5 - Planning",
        action: "Demoted from P1 to P5",
        justification: "Rule TR-001: Cosmetic UI issue without transactional disruption.",
        sla: "Resolution Target: Next Sprint",
      });
    } else if (lower.includes("billing") || lower.includes("payment") || lower.includes("settlement")) {
      setSimulatedResult({
        normalized: "1 - Critical",
        action: "Promoted to P1 Critical",
        justification: "Rule TR-003: Core financial transaction bottleneck.",
        sla: "Resolution Target: 4 Hours (15 min response)",
      });
    } else {
      setSimulatedResult({
        normalized: "3 - Moderate",
        action: "Standard Operating Alignment",
        justification: "Aligned with AMS Runbook standard business impact taxonomy.",
        sla: "Resolution Target: 24 Hours",
      });
    }
  };

  return (
    <AgentWorkflowLayout currentStep={2}>
      <PageHeader
        title="Triage"
        context="Re-evaluates the priority of validated tickets against business impact rules and overrides inflated reporter priorities."
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] [&>*:first-child]:col-span-2 sm:[&>*:first-child]:col-span-1">
        <StatTile variant="primary" label="Active policies" value={TRIAGE_RULES.length} />
        <StatTile label="Promote priority" value={promotedCount} />
        <StatTile label="Demote priority" value={demotedCount} />
      </div>

      <Card className="gap-0 py-0">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Priority reclassification policies</h2>
          <p className="text-xs text-muted-foreground">
            Policies that normalize ticket urgency based on business impact.
          </p>
        </div>
        <ul role="list">
          {TRIAGE_RULES.map((rule) => (
            <ListRow
              key={rule.id}
              lead={<PriorityChange from={rule.reported} to={rule.normalized} />}
              itemKey={rule.id}
              title={rule.condition}
              meta={`${rule.impactTier} · ${rule.rationale}`}
              trailing={
                <span className="inline-flex items-center gap-1.5">
                  <CircleCheck className="size-4" aria-hidden="true" />
                  {rule.status}
                </span>
              }
            />
          ))}
        </ul>
      </Card>

      <Card className="gap-4 px-4">
        <div>
          <h2 className="text-sm font-semibold">Try a ticket</h2>
          <p className="text-xs text-muted-foreground">
            See how the Triage Agent adjusts a reported priority under the policies above.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-3 sm:items-end">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="triage-app" className="text-xs font-medium text-foreground">Target application</label>
            <select
              id="triage-app"
              value={selectedApp}
              onChange={(e) => setSelectedApp(e.target.value)}
              className={SELECT_CLASS}
            >
              <option value="SalesConnect CRM">SalesConnect CRM (Tier 2)</option>
              <option value="BillingEngine">BillingEngine (Tier 1)</option>
              <option value="StockSense">StockSense (Tier 2)</option>
              <option value="InsightBI">InsightBI (Tier 3)</option>
              <option value="PayrollPro">PayrollPro (Tier 1)</option>
              <option value="EmployeePortal">EmployeePortal (Tier 3)</option>
              <option value="OrderHub">OrderHub (Tier 2)</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="triage-reported" className="text-xs font-medium text-foreground">Reported priority</label>
            <select
              id="triage-reported"
              value={reportedPriority}
              onChange={(e) => setReportedPriority(e.target.value)}
              className={SELECT_CLASS}
            >
              <option value="1 - Critical">1 - Critical (Claims Emergency)</option>
              <option value="2 - High">2 - High</option>
              <option value="3 - Moderate">3 - Moderate</option>
              <option value="4 - Low">4 - Low</option>
            </select>
          </div>

          <Button onClick={handleSimulateTriage}>
            <Scale />
            Evaluate priority
          </Button>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="triage-summary" className="text-xs font-medium text-foreground">Short description</label>
          <Input
            id="triage-summary"
            type="text"
            value={ticketSummary}
            onChange={(e) => setTicketSummary(e.target.value)}
            placeholder="Describe the reported issue..."
          />
        </div>

        {simulatedResult && (
          <div role="status" className="flex flex-col gap-2 rounded-lg border border-border bg-muted p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[13px] font-semibold text-foreground">Verdict: {simulatedResult.action}</span>
              <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                Normalized
                <PriorityChip level={levelOf(simulatedResult.normalized)} />
                {simulatedResult.normalized}
              </span>
            </div>
            <p className="text-body">
              <span className="font-medium text-foreground">Policy justification:</span> {simulatedResult.justification}
            </p>
            <div className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="size-4" aria-hidden="true" />
              {simulatedResult.sla}
            </div>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
        <Card className="gap-0 py-0">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold">Contracted SLA targets</h2>
          </div>
          <ul role="list">
            {SLA_MATRIX.map((tier) => (
              <ListRow
                key={tier.priority}
                lead={<PriorityChip level={levelOf(tier.priority)} />}
                title={tier.priority.replace(/^P\d - /, "")}
                meta={`Response ${tier.targetResponse} · Resolution ${tier.targetResolution}`}
              />
            ))}
          </ul>
        </Card>

        <Card className="gap-1 px-4">
          <h2 className="text-sm font-semibold">Input from Data Quality</h2>
          <p className="text-body">
            Consumes only clean tickets where the Data Quality flag is valid (<span className="font-mono text-foreground">dq_flag = false</span>) and personal caller data has been masked via Presidio.
          </p>
        </Card>

        <Card className="gap-1 px-4">
          <h2 className="text-sm font-semibold">Objective reclassification</h2>
          <p className="text-body">
            Prevents queue saturation caused by subjective user submissions. Maps true operational criticality to contracted SLA response windows.
          </p>
        </Card>

        <Card className="gap-1 px-4">
          <h2 className="text-sm font-semibold">Hand-off to Resolution</h2>
          <p className="text-body">
            Triaged and prioritized incidents are passed to the Resolution Agent for automated runbook lookup and remediation drafting.
          </p>
        </Card>
      </div>
    </AgentWorkflowLayout>
  );
}
