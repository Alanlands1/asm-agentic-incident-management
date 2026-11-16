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
import { CircleCheck, Search, Copy, Check } from "lucide-react";

interface KBArticle {
  id: string;
  appId: string;
  appName: string;
  title: string;
  criticality: "Tier 1" | "Tier 2" | "Tier 3";
  rootCause: string;
  resolutionSummary: string;
}

const KB_ARTICLES: KBArticle[] = [
  {
    id: "KB-CRM-001",
    appId: "APP-CRM",
    appName: "SalesConnect CRM",
    title: "User account locked / cannot log in",
    criticality: "Tier 2",
    rootCause: "Platform lockout policy (5 failed attempts, 30-minute lock)",
    resolutionSummary: "Admin console → Users → Unlock. If forgotten password, trigger reset link to corporate email.",
  },
  {
    id: "KB-CRM-002",
    appId: "APP-CRM",
    appName: "SalesConnect CRM",
    title: "Opportunity stage update failed / Validation Error",
    criticality: "Tier 2",
    rootCause: "Missing mandatory fields during end-of-stage gate transition",
    resolutionSummary: "Verify opportunity close date and discount threshold approval flag in MuleSoft sync log.",
  },
  {
    id: "KB-BIL-001",
    appId: "APP-BIL",
    appName: "BillingEngine",
    title: "Payment gateway webhook timeout / settlement failure",
    criticality: "Tier 1",
    rootCause: "Webhook queue consumer backpressure exceeding 300s timeout",
    resolutionSummary: "Restart settlement worker pod pool, flush dead-letter Redis queue, trigger idempotent replay.",
  },
  {
    id: "KB-STK-001",
    appId: "APP-STK",
    appName: "StockSense",
    title: "Warehouse inventory discrepancy on SKU stock count",
    criticality: "Tier 2",
    rootCause: "Stale Kafka partition offset in warehouse event ingestion pipeline",
    resolutionSummary: "Re-index warehouse stock batch via reconciliation CLI tool `stocksense-reconcile --facility=WH-EAST`.",
  },
  {
    id: "KB-PAY-001",
    appId: "APP-PAY",
    appName: "PayrollPro",
    title: "Direct deposit batch transmission lock",
    criticality: "Tier 1",
    rootCause: "NACHA formatted file encryption key expiry on banking SFTP channel",
    resolutionSummary: "Rotate PGP bank transfer key via Key Vault, verify test batch checksum, re-trigger payroll run.",
  },
  {
    id: "KB-BI-001",
    appId: "APP-BI",
    appName: "InsightBI",
    title: "Executive dashboard refresh failure (Nightly ETL)",
    criticality: "Tier 3",
    rootCause: "Snowflake warehouse auto-suspend during long-running dimension join",
    resolutionSummary: "Scale warehouse to Large, execute partition refresh script `dbt run --select marts.sales`.",
  },
  {
    id: "KB-PORTAL-001",
    appId: "APP-PORTAL",
    appName: "EmployeePortal",
    title: "Benefits enrollment single sign-on redirect loop",
    criticality: "Tier 3",
    rootCause: "SAML assertion signature certificate mismatch in identity provider",
    resolutionSummary: "Update IdP metadata XML in Azure AD enterprise application settings.",
  },
];

export default function ResolutionPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedApp, setSelectedApp] = useState("ALL");
  const [selectedArticle, setSelectedArticle] = useState<KBArticle | null>(KB_ARTICLES[0]);
  const [copied, setCopied] = useState(false);

  const filteredArticles = KB_ARTICLES.filter((item) => {
    const matchesSearch =
      item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.rootCause.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesApp = selectedApp === "ALL" || item.appName === selectedApp;
    return matchesSearch && matchesApp;
  });

  const handleCopyDraft = () => {
    if (!selectedArticle) return;
    const text = `Resolution Plan for ${selectedArticle.id} (${selectedArticle.appName}):\nRoot Cause: ${selectedArticle.rootCause}\nSteps:\n1. ${selectedArticle.resolutionSummary}\n2. Verify incident logs and confirm with reporter.`;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <AgentWorkflowLayout currentStep={3}>
      <PageHeader
        title="Resolution"
        context="Searches application runbooks for triaged incidents and drafts resolution steps."
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <StatTile variant="primary" label="Runbooks indexed" value={7} />
        <StatTile label="Core applications" value={7} />
      </div>

      <div className="grid items-start gap-4 min-[1100px]:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="gap-0 py-0">
          <div className="flex flex-col gap-3 border-b border-border px-4 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-sm font-semibold">Application runbooks and error patterns</h2>
              <span className="text-xs text-muted-foreground tabular-nums">{filteredArticles.length} articles</span>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted-foreground" aria-hidden="true" />
                <Input
                  type="text"
                  aria-label="Search runbooks"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by KB code, symptom, or root cause..."
                  className="pl-8"
                />
              </div>
              <select
                aria-label="Application"
                value={selectedApp}
                onChange={(e) => setSelectedApp(e.target.value)}
                className="h-8 rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none transition-colors duration-[80ms] focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <option value="ALL">All Applications</option>
                <option value="SalesConnect CRM">SalesConnect CRM</option>
                <option value="BillingEngine">BillingEngine</option>
                <option value="StockSense">StockSense</option>
                <option value="InsightBI">InsightBI</option>
                <option value="PayrollPro">PayrollPro</option>
                <option value="EmployeePortal">EmployeePortal</option>
              </select>
            </div>
          </div>
          <ul role="list">
            {filteredArticles.map((article) => {
              const isSelected = selectedArticle?.id === article.id;
              return (
                <ListRow
                  key={article.id}
                  className={`relative transition-colors duration-[80ms] ${isSelected ? "bg-selected" : "hover:bg-accent"}`}
                  itemKey={article.id}
                  title={
                    <button
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => setSelectedArticle(article)}
                      className="rounded-sm text-left outline-none after:absolute after:inset-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                      {article.title}
                    </button>
                  }
                  meta={`${article.appName} · Root cause: ${article.rootCause}`}
                  trailing={<Badge>{article.criticality}</Badge>}
                />
              );
            })}
          </ul>
        </Card>

        {selectedArticle ? (
          <Card className="gap-0 py-0">
            <div className="flex flex-col gap-1 border-b border-border px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-muted-foreground">{selectedArticle.id}</span>
                <Badge>{selectedArticle.appId}</Badge>
              </div>
              <h2 className="text-sm font-semibold text-foreground">{selectedArticle.title}</h2>
              <p className="text-xs text-muted-foreground">
                Target system: {selectedArticle.appName} · {selectedArticle.criticality}
              </p>
            </div>

            <div className="flex flex-col gap-4 px-4 py-4">
              <div className="flex flex-col gap-1">
                <h3 className="text-xs font-medium text-muted-foreground">Identified root cause</h3>
                <p className="rounded-lg bg-muted p-2.5 text-body">{selectedArticle.rootCause}</p>
              </div>

              <div className="flex flex-col gap-1.5">
                <h3 className="text-xs font-medium text-muted-foreground">Prescribed remediation steps</h3>
                <ol className="flex flex-col gap-2">
                  {[
                    selectedArticle.resolutionSummary,
                    "Verify service health logs and validate caller confirmation.",
                    "Mark incident resolved with Presidio-masked caller audit trail.",
                  ].map((step, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="grid size-5 shrink-0 place-items-center rounded-full bg-selected text-xs font-semibold tabular-nums">
                        {i + 1}
                      </span>
                      <span className={i === 0 ? "text-foreground" : "text-body"}>{step}</span>
                    </li>
                  ))}
                </ol>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <CircleCheck className="size-4" aria-hidden="true" />
                  Runbook verified, ready for deployment
                </span>
                <Button size="sm" variant="secondary" onClick={handleCopyDraft}>
                  {copied ? <Check /> : <Copy />}
                  {copied ? "Copied" : "Copy draft"}
                </Button>
              </div>
            </div>
          </Card>
        ) : (
          <Card className="px-4 text-center text-muted-foreground">
            Select an article to inspect its synthesized resolution plan.
          </Card>
        )}
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
        <Card className="gap-1 px-4">
          <h2 className="text-sm font-semibold">Validated and triaged input</h2>
          <p className="text-body">
            Receives incidents that have passed deterministic Data Quality checks (Step 1) and have had their operational priority normalized (Step 2).
          </p>
        </Card>
        <Card className="gap-1 px-4">
          <h2 className="text-sm font-semibold">Knowledge base corpus</h2>
          <p className="text-body">
            Indexes standard runbooks across CRM, Billing, Inventory, BI, Payroll, Employee Portal, and Order Hub architectures.
          </p>
        </Card>
        <Card className="gap-1 px-4">
          <h2 className="text-sm font-semibold">Resolution output</h2>
          <p className="text-body">
            Synthesizes root causes, exact CLI / Admin console remediation steps, and safe rollback verification for AMS support engineers.
          </p>
        </Card>
      </div>
    </AgentWorkflowLayout>
  );
}
