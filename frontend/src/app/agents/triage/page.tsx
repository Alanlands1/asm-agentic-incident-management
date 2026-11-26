import { AgentPage } from "@/components/console/agent-page";

export default function TriageAgentPage() {
  return (
    <AgentPage
      title="Triage"
      agent="triage"
      context="Recommends a priority with a rationale, detects storms and drafts the first P1/P2 update. An engineer confirms the priority."
      prefix="TRIAGE"
      breakerKey="TRIAGE_OUTAGE_BREAKER"
      documents={[
        { name: "triage_rules", label: "Rules" },
        { name: "triage_jobs", label: "Batch jobs" },
        {
          name: "data_quality_prompts",
          label: "Prompts",
          note: "All agents share one prompts file: a change here also affects the Data Quality prompt.",
        },
      ]}
    />
  );
}
