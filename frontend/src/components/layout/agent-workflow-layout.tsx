"use client";

import Link from "next/link";
import { AppShell } from "@/components/console/app-shell";
import { Button } from "@/components/ui/button";
import { ArrowLeft, ArrowRight } from "lucide-react";

interface AgentWorkflowLayoutProps {
  children: React.ReactNode;
  currentStep: 1 | 2 | 3;
}

const STEPS = [
  { step: 1, title: "Data Quality", href: "/dq-rules" },
  { step: 2, title: "Triage", href: "/triage" },
  { step: 3, title: "Resolution", href: "/resolution" },
];

export function AgentWorkflowLayout({ children, currentStep }: AgentWorkflowLayoutProps) {
  const prevStep = currentStep > 1 ? STEPS[currentStep - 2] : null;
  const nextStep = currentStep < 3 ? STEPS[currentStep] : null;

  return (
    <AppShell>
      {children}

      {/* Quiet pipeline navigation */}
      <nav aria-label="Pipeline" className="mt-8 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-4">
        <Button variant="secondary" render={<Link href={prevStep ? prevStep.href : "/"} />} nativeButton={false}>
          <ArrowLeft />
          {prevStep ? `Back: ${prevStep.title}` : "Back to overview"}
        </Button>
        <Button variant="secondary" render={<Link href={nextStep ? nextStep.href : "/"} />} nativeButton={false}>
          {nextStep ? `Next: ${nextStep.title}` : "Pipeline complete: overview"}
          <ArrowRight />
        </Button>
      </nav>
    </AppShell>
  );
}
