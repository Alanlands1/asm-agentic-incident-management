import { AgentPage } from "@/components/console/agent-page";

export default function TriageAgentPage() {
  return (
    <AgentPage
      title="Triage"
      agent="triage"
      context="Recommends a priority with a reason, finds storms and drafts the P1/P2 first message. An engineer decides."
      prefix="TRIAGE"
      breakerKey="TRIAGE_OUTAGE_BREAKER"
      documents={[
        { name: "triage_rules", label: "Rules" },
        { name: "triage_jobs", label: "Batch jobs" },
        {
          name: "data_quality_prompts",
          label: "Prompts",
          note: "One prompts file serves every agent: a change here also changes Data Quality's prompt.",
        },
      ]}
    />
  );
}
