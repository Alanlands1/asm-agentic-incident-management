"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CheckCircle2,
  ShieldAlert,
  BookOpen,
  ArrowRight,
  ShieldCheck,
  Home,
  FileCode2,
  Lock,
  Layers,
  ChevronRight
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface AgentStep {
  step: number;
  id: string;
  title: string;
  stageName: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  tag: string;
  description: string;
  accentColor: string;
  activeBg: string;
  activeBorder: string;
}

const AGENT_STEPS: AgentStep[] = [
  {
    step: 1,
    id: "data-quality",
    title: "Data Quality Agent",
    stageName: "Step 01",
    href: "/dq-rules",
    icon: CheckCircle2,
    tag: "Deterministic Validation",
    description: "Evaluates incident quality, masks PII, and flags defective tickets.",
    accentColor: "text-[#a20a29]",
    activeBg: "bg-[#fdf2f4]",
    activeBorder: "border-[#a20a29]",
  },
  {
    step: 2,
    id: "triage",
    title: "Triage & Priority Agent",
    stageName: "Step 02",
    href: "/triage",
    icon: ShieldAlert,
    tag: "Runbook SLA Alignment",
    description: "Normalizes misclassified priorities against enterprise SLA runbooks.",
    accentColor: "text-[#005656]",
    activeBg: "bg-[#f0f4f4]",
    activeBorder: "border-[#005656]",
  },
  {
    step: 3,
    id: "resolution",
    title: "Resolution Agent",
    stageName: "Step 03",
    href: "/resolution",
    icon: BookOpen,
    tag: "Knowledge Base Runbooks",
    description: "Matches known error patterns to synthesize verified remediation drafts.",
    accentColor: "text-[#b08824]",
    activeBg: "bg-[#fbf7ee]",
    activeBorder: "border-[#b08824]",
  },
];

export function AgentSidebar({ currentStep }: { currentStep?: number }) {
  const pathname = usePathname();

  return (
    <aside className="w-72 shrink-0 border-r border-[#e0e1dc] bg-white flex flex-col justify-between min-h-[calc(100vh-3.75rem)] sticky top-15">
      <div className="p-4 space-y-6">
        {/* Navigation Section Header */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[#005656]">
              Agent Pipeline Steps
            </span>
            <span className="text-[10px] font-semibold text-[#5e605d] bg-[#f0f4f4] px-2 py-0.5 rounded">
              3 Stages
            </span>
          </div>
          <p className="text-xs text-[#5e605d] leading-tight">
            Follow the sequential pipeline flow or switch between specialized agents.
          </p>
        </div>

        {/* Sequential Step List */}
        <nav className="space-y-2">
          {/* Direct Incident Repository Link */}
          <Link
            href="/tickets"
            className={`group block rounded-lg border p-3 transition-all ${
              pathname === "/tickets"
                ? "bg-[#f0f4f4] border-[#005656] shadow-xs"
                : "border-[#e0e1dc] bg-white hover:bg-[#fbfbfb] hover:border-[#cfd1cc]"
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Layers className={`h-4 w-4 ${pathname === "/tickets" ? "text-[#005656]" : "text-[#5e605d]"}`} />
                <span className="text-xs font-bold text-[#222222]">Incident Repository</span>
              </div>
              <Badge variant="outline" className="text-[10px] border-[#e0e1dc] bg-[#fbfbfb] text-[#5e605d]">
                Tickets
              </Badge>
            </div>
            <p className="text-[11px] text-[#5e605d] mt-1 line-clamp-1">
              Browse all ingested ServiceNow incidents & PII records.
            </p>
          </Link>

          {AGENT_STEPS.map((stepItem) => {
            const Icon = stepItem.icon;
            const isDQ = stepItem.id === "data-quality";
            const isDQActive = pathname.startsWith("/dq-rules");
            const isActive = isDQ ? isDQActive : (currentStep === stepItem.step || pathname === stepItem.href);
            const isCompleted = currentStep ? currentStep > stepItem.step : false;

            return (
              <div key={stepItem.id} className="space-y-1">
                <Link
                  href={stepItem.href}
                  className={`group block rounded-lg border p-3.5 transition-all ${
                    isActive
                      ? `${stepItem.activeBg} ${stepItem.activeBorder} shadow-xs`
                      : "border-[#e0e1dc] bg-white hover:bg-[#fbfbfb] hover:border-[#cfd1cc]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <div className="flex items-center gap-2">
                      <div
                        className={`h-6 w-6 rounded flex items-center justify-center text-xs font-bold ${
                          isActive
                            ? "bg-[#a20a29] text-white"
                            : isCompleted
                            ? "bg-[#005656] text-white"
                            : "bg-[#f0f4f4] text-[#5e605d]"
                        }`}
                      >
                        {stepItem.step}
                      </div>
                      <span className="text-[11px] font-semibold text-[#5e605d] uppercase tracking-wide">
                        {stepItem.stageName}
                      </span>
                    </div>

                    {isActive ? (
                      <Badge className="bg-[#a20a29] text-white text-[10px] px-1.5 py-0 h-4 border-none">
                        Active
                      </Badge>
                    ) : isCompleted ? (
                      <span className="text-[10px] font-medium text-[#005656] flex items-center gap-0.5">
                        ✓ Done
                      </span>
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-[#5e605d] opacity-50 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                    )}
                  </div>

                  <div className="flex items-center gap-2 text-xs font-bold text-[#222222] mb-1">
                    <Icon className={`h-4 w-4 ${isActive ? stepItem.accentColor : "text-[#5e605d]"}`} />
                    <span className="truncate">{stepItem.title}</span>
                  </div>

                  <p className="text-[11px] text-[#5e605d] leading-normal line-clamp-2">
                    {stepItem.description}
                  </p>
                </Link>

                {/* Sub-navigation for Data Quality */}
                {isDQ && isDQActive && (
                  <div className="ml-4 pl-3 border-l-2 border-[#a20a29]/30 space-y-1 pt-1">
                    <Link
                      href="/dq-rules"
                      className={`block px-2.5 py-1 text-xs rounded transition-colors ${
                        pathname === "/dq-rules"
                          ? "bg-[#fdf2f4] text-[#a20a29] font-bold"
                          : "text-[#5e605d] hover:text-[#222222] hover:bg-[#f0f4f4]"
                      }`}
                    >
                      • Manage Rules
                    </Link>
                    <Link
                      href="/dq-rules/execute"
                      className={`block px-2.5 py-1 text-xs rounded transition-colors ${
                        pathname === "/dq-rules/execute"
                          ? "bg-[#f0f4f4] text-[#005656] font-bold"
                          : "text-[#5e605d] hover:text-[#222222] hover:bg-[#f0f4f4]"
                      }`}
                    >
                      • Execute & Audit Runs
                    </Link>
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* Pipeline Verification Status */}
        <div className="rounded-lg border border-[#e0e1dc] bg-[#fbfbfb] p-3 space-y-2.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-[#222222]">
            <Layers className="h-3.5 w-3.5 text-[#005656]" />
            <span>Architecture Guarantees</span>
          </div>

          <div className="space-y-1.5 text-[11px] text-[#5e605d]">
            <div className="flex items-center gap-2">
              <Lock className="h-3 w-3 text-[#005656] shrink-0" />
              <span>Presidio PII Redaction Active</span>
            </div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-3 w-3 text-[#a20a29] shrink-0" />
              <span>Deterministic Gate Verification</span>
            </div>
          </div>
        </div>
      </div>

      {/* Sidebar Footer Navigation */}
      <div className="p-4 border-t border-[#e0e1dc] space-y-2 bg-white">
        <Link
          href="/"
          className="flex items-center gap-2 text-xs font-medium text-[#5e605d] hover:text-[#222222] p-2 rounded-md hover:bg-[#f0f4f4] transition-colors"
        >
          <Home className="h-3.5 w-3.5 text-[#005656]" />
          <span>Platform Overview</span>
        </Link>
        <a
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 text-xs font-medium text-[#5e605d] hover:text-[#222222] p-2 rounded-md hover:bg-[#f0f4f4] transition-colors"
        >
          <FileCode2 className="h-3.5 w-3.5 text-[#a20a29]" />
          <span>OpenAPI Interactive Docs</span>
        </a>
      </div>
    </aside>
  );
}
