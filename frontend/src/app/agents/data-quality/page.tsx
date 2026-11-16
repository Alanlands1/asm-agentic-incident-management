import Link from "next/link";
import { AgentPage } from "@/components/console/agent-page";
import { Card } from "@/components/ui/card";

const SHARED_PROMPTS = "One prompts file serves every agent: a change here also changes Triage's prompt.";

export default function DataQualityAgentPage() {
  return (
    <AgentPage
      title="Data Quality"
      agent="data_quality"
      context="Checks each new ticket has what an engineer needs, and drafts questions for the reporter when it does not."
      prefix="DQ"
      breakerKey="DQ_OUTAGE_BREAKER"
      documents={[
        { name: "data_quality_rules", label: "Rules" },
        { name: "data_quality_prompts", label: "Prompts", note: SHARED_PROMPTS },
      ]}
      extra={
        <Card className="px-4 py-3 text-[13px]">
          <p>
            The Flagged and Clean labels on All tickets come from a separate set of rules, the rule builder.{" "}
            <Link href="/dq-rules" className="font-semibold text-primary underline-offset-4 hover:underline">
              Open the rule builder
            </Link>
          </p>
        </Card>
      }
    />
  );
}
